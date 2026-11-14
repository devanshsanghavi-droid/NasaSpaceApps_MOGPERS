"""Shared, causal feature construction for the Field to Faucet river nitrate model.

Every rolling quantity at day t uses only data from days <= t (trailing windows).
Used by m01_features.py (to build model/out/features.parquet) and by river.py
(to recompute cover-derived features after a counterfactual change of bare share).

Inputs (data/processed/, owners in brackets):
  nwis_daily.parquet [hydro]        site, date, no3_mgL, q_cfs
  power_daily_basin.parquet [hydro] basin, date, PRECTOTCORR, GWETROOT, GWETTOP, T2M, SNODP
  cover_basin_daily.parquet [modis] basin, date, bare_share, living_share, gap_days, filled
  cdl_basin_year.parquet [cdl]      basin, year, corn
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
PROC = APP / "data" / "processed"
OUT = APP / "model" / "out"

SITES = {"05484500": "raccoon", "05482000": "desmoines"}
SITE_NAMES = {"05484500": "Raccoon River at Van Meter", "05482000": "Des Moines River at 2nd Ave, Des Moines"}

TRAIN = ("2016-01-01", "2022-12-31")
TEST = ("2023-01-01", "2025-12-31")
LIVE_START = "2026-01-01"

# A MODIS gap longer than this (days between bracketing composites) is not trusted as a
# straight-line interpolation: harvest/green-up are strongly non-linear in time. Such days
# are replaced by the day-of-year climatology (2016-2024, non-filled days) and flagged.
LONG_GAP_DAYS = 60

RAIN_WIN = [1, 3, 7, 14, 30, 60, 90, 180, 365]
API_K = {"api_k85": 0.85, "api_k95": 0.95, "api_k98": 0.98}


def split_of(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates)
    s = pd.Series("pre", index=dates.index, dtype=object)
    s[(d >= TRAIN[0]) & (d <= TRAIN[1])] = "train"
    s[(d >= TEST[0]) & (d <= TEST[1])] = "test"
    s[d >= LIVE_START] = "live"
    return s


def _roll_sum(x: pd.Series, w: int) -> pd.Series:
    return x.rolling(w, min_periods=max(1, int(0.8 * w))).sum()


def _roll_mean(x: pd.Series, w: int) -> pd.Series:
    return x.rolling(w, min_periods=max(1, int(0.8 * w))).mean()


def _api(p: np.ndarray, k: float) -> np.ndarray:
    out = np.empty_like(p, dtype=float)
    acc = 0.0
    for i, v in enumerate(p):
        acc = k * acc + (0.0 if np.isnan(v) else v)
        out[i] = acc
    return out


def doy_climatology(dates: pd.Series, values: pd.Series, years=(2016, 2024), halfwin: int = 7) -> pd.Series:
    """Day-of-year mean (circular +-halfwin smoothing) of `values` over the given years; index 1..366."""
    d = pd.to_datetime(dates)
    m = (d.dt.year >= years[0]) & (d.dt.year <= years[1]) & values.notna()
    doy = d[m].dt.dayofyear.clip(upper=365)
    raw = values[m].groupby(doy.values).mean().reindex(range(1, 366))
    raw = raw.interpolate(limit_direction="both")
    arr = raw.values
    ext = np.concatenate([arr[-halfwin:], arr, arr[:halfwin]])
    sm = np.convolve(ext, np.ones(2 * halfwin + 1) / (2 * halfwin + 1), mode="valid")
    s = pd.Series(sm, index=range(1, 366))
    s.loc[366] = s.loc[365]
    return s


def load_raw(proc: Path = PROC) -> pd.DataFrame:
    """One continuous daily frame per site with raw daily drivers (no rolling yet)."""
    nw = pd.read_parquet(proc / "nwis_daily.parquet")
    nw["date"] = pd.to_datetime(nw["date"])
    pw = pd.read_parquet(proc / "power_daily_basin.parquet")
    pw["date"] = pd.to_datetime(pw["date"])
    cv = pd.read_parquet(proc / "cover_basin_daily.parquet")
    cv["date"] = pd.to_datetime(cv["date"])
    cdl = pd.read_parquet(proc / "cdl_basin_year.parquet")

    frames = []
    for site, basin in SITES.items():
        p = pw[pw.basin == basin].set_index("date").sort_index()
        start = p.index.min()
        end = max(p.index.max(), nw.loc[nw.site == site, "date"].max())
        idx = pd.date_range(start, end, freq="D")
        df = pd.DataFrame(index=idx)
        df.index.name = "date"
        df["site"] = site
        df["basin"] = basin
        df["P"] = p["PRECTOTCORR"].astype(float)
        df["gwr"] = p["GWETROOT"].astype(float)
        df["gwt"] = p["GWETTOP"].astype(float)
        df["t2m"] = p["T2M"].astype(float)
        df["snodp"] = p["SNODP"].astype(float)
        df["power_ok"] = df["P"].notna() & df["gwr"].notna() & df["t2m"].notna()

        n = nw[nw.site == site].set_index("date")
        df["no3"] = n["no3_mgL"]
        df["q_cfs"] = n["q_cfs"]
        df["no3_qual"] = n["no3_qual"]

        # ---- cover (MODIS) with transparent handling of long gaps and the trailing edge
        c = cv[cv.basin == basin].set_index("date").sort_index()
        bare = c["bare_share"].astype(float).reindex(idx)
        gap = c["gap_days"].reindex(idx)
        filled = c["filled"].reindex(idx).fillna(False).astype(bool)
        good = bare.notna() & ~filled
        clim = doy_climatology(pd.Series(idx), pd.Series(bare.where(good).values), years=(2016, 2024))
        clim_today = pd.Series(clim.reindex(idx.dayofyear).values, index=idx)
        src = pd.Series("modis", index=idx, dtype=object)
        src[filled & (gap <= LONG_GAP_DAYS)] = "modis_interp"
        longgap = filled & (gap > LONG_GAP_DAYS)
        df["bare_share_provided"] = bare  # as delivered by the modis module (for robustness runs)
        bare = bare.where(~longgap, clim_today)
        src[longgap] = "clim_longgap"
        # trailing edge: decay last anomaly toward climatology with e-folding 30 d
        last = c["bare_share"].dropna().index.max()
        if last is not None and last < idx[-1]:
            anom = float(c.loc[last, "bare_share"]) - float(clim.loc[min(last.dayofyear, 366)])
            tail = idx[idx > last]
            lag = (tail - last).days.values
            bare.loc[tail] = np.clip(clim_today.loc[tail].values + anom * np.exp(-lag / 30.0), 0, 1)
            src.loc[tail] = "extrap"
        # head (before MODIS start): climatology
        head = bare.isna() & (idx < (c.index.min() if len(c) else idx[-1]))
        bare[head] = clim_today[head]
        src[head] = "clim_head"
        df["bare"] = bare.clip(0, 1)
        df["living"] = 1.0 - df["bare"]  # living + bare = 1 over valid row-crop pixels
        df["cover_src"] = src

        # ---- CDL corn share (2016-2025). 2015 uses 2016; 2026 uses 2025 (persistence; flagged)
        cb = cdl[cdl.basin == basin].set_index("year")["corn"].astype(float)
        yrs = df.index.year
        def corn_for(y):
            y2 = min(max(y, cb.index.min()), cb.index.max())
            return float(cb.loc[y2])
        df["corn_y"] = [corn_for(y) for y in yrs]
        df["corn_prev"] = [corn_for(y - 1) for y in yrs]
        df["cdl_extrap"] = (yrs > cb.index.max()) | (yrs - 1 < cb.index.min())
        frames.append(df.reset_index())
    return pd.concat(frames, ignore_index=True)


def cover_features(g: pd.DataFrame) -> pd.DataFrame:
    """(Re)compute cover-derived features for ONE site's continuous daily frame from columns
    bare, P, gwr. Used both for the base features and for counterfactual perturbations."""
    g = g.copy()
    g["living"] = 1.0 - g["bare"]
    g["bare_30"] = _roll_mean(g["bare"], 30)
    g["bare_90"] = _roll_mean(g["bare"], 90)
    g["bare_180"] = _roll_mean(g["bare"], 180)
    g["living_30"] = 1.0 - g["bare_30"]
    bw = g["bare"] * g["P"] * g["gwr"]  # rain landing on bare, wet soil (mm-equivalent)
    g["barewet_30"] = _roll_sum(bw, 30)
    g["barewet_90"] = _roll_sum(bw, 90)
    return g


def site_features(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").reset_index(drop=True).copy()
    P = g["P"]
    for w in RAIN_WIN:
        g[f"rain_{w}"] = P if w == 1 else _roll_sum(P, w)
    for name, k in API_K.items():
        g[name] = _api(P.values, k)
    g.loc[~g["power_ok"], list(API_K)] = np.nan
    for v in ["gwr", "gwt"]:
        g[f"{v}_7"] = _roll_mean(g[v], 7)
        g[f"{v}_30"] = _roll_mean(g[v], 30)
    g["gwr_90"] = _roll_mean(g["gwr"], 90)
    g["gwr_365"] = _roll_mean(g["gwr"], 365)
    wr = P * g["gwr"]
    g["wetrain_7"] = _roll_sum(wr, 7)
    g["wetrain_30"] = _roll_sum(wr, 30)
    g["wetrain_90"] = _roll_sum(wr, 90)
    melt = (-g["snodp"].diff()).clip(lower=0)
    g["melt_7"] = _roll_sum(melt, 7)
    g["melt_30"] = _roll_sum(melt, 30)
    g["t2m_7"] = _roll_mean(g["t2m"], 7)
    g["t2m_30"] = _roll_mean(g["t2m"], 30)
    # degree-days (base 5 C) since the most recent Mar 1 (soil N mineralization proxy)
    d = pd.to_datetime(g["date"])
    season_year = np.where(d.dt.month >= 3, d.dt.year, d.dt.year - 1)
    dd = (g["t2m"] - 5).clip(lower=0).fillna(0)
    g["gdd5_mar1"] = dd.groupby(season_year).cumsum().values
    g = cover_features(g)
    # streamflow (observed driver). Missing Q is not interpolated.
    lq = np.log(g["q_cfs"].where(g["q_cfs"] > 0))
    g["logq"] = lq
    g["logq_7"] = _roll_mean(lq, 7)
    g["logq_30"] = _roll_mean(lq, 30)
    g["dlogq"] = lq.diff()
    g["dlogq_7"] = lq - lq.shift(7)
    doy = d.dt.dayofyear
    g["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    g["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    # days without POWER (the ~2-3 day POWER latency at the end): weather features are unknown,
    # never computed from partial windows
    wcols = ([f"rain_{w}" for w in RAIN_WIN] + list(API_K) + ["gwr_7", "gwt_7", "gwr_30", "gwt_30", "gwr_90",
             "gwr_365", "wetrain_7", "wetrain_30", "wetrain_90", "melt_7", "melt_30", "t2m_7", "t2m_30",
             "gdd5_mar1", "barewet_30", "barewet_90"])
    g.loc[~g["power_ok"].astype(bool), wcols] = np.nan
    g["year"] = d.dt.year
    g["split"] = split_of(g["date"]).values
    g["lno3"] = np.log(g["no3"].where(g["no3"] > 0))
    return g


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([site_features(g) for _, g in raw.groupby("site")], ignore_index=True)


# ---- feature sets and monotone constraints for the simulation GBM ----------------------------
BARE_FEATS = ["bare", "bare_30", "bare_90", "bare_180"]
BAREWET_FEATS = ["barewet_30", "barewet_90"]
WET_FEATS = ["gwr", "gwt", "gwr_7", "gwt_7", "gwr_30", "gwt_30", "gwr_90"]
OTHER_FEATS = (
    [f"rain_{w}" for w in [1, 3, 7, 14, 30, 60, 90, 180]]
    + list(API_K)
    + ["wetrain_7", "wetrain_30", "wetrain_90", "melt_7", "melt_30", "snodp",
       "t2m_7", "t2m_30", "gdd5_mar1", "logq", "logq_7", "logq_30", "dlogq", "dlogq_7",
       "doy_sin", "doy_cos"]
)
LONGMEM_FEATS = ["rain_365", "gwr_365"]  # multi-season memory (legacy N after drought); CV decides
CDL_FEATS = ["corn_y", "corn_prev"]       # year-constant; CV decides (risk: acts as a year id)
COVER_DERIVED = ["living", "living_30", "bare_30", "bare_90", "bare_180", "barewet_30", "barewet_90"]


def gbm_features(use_longmem: bool, use_cdl: bool) -> list[str]:
    f = BARE_FEATS + BAREWET_FEATS + WET_FEATS + OTHER_FEATS
    if use_longmem:
        f = f + LONGMEM_FEATS
    if use_cdl:
        f = f + CDL_FEATS
    return f


def monotone_vector(feats: list[str]) -> list[int]:
    pos = set(BARE_FEATS + BAREWET_FEATS + WET_FEATS)
    return [1 if f in pos else 0 for f in feats]
