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

# Cover must be CAUSAL: on day t only composites whose 16-day window ended >= ASOF_LAG days
# before t are usable (the provided daily file's centred interpolation peeks ~16-30 d ahead).
ASOF_LAG = 3
FRESH_AGE = 24      # days; an as-of value older than this decays toward climatology
STALE_EFOLD = 30.0  # e-folding (days) of the last anomaly once stale

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


def cover_asof(cv: pd.DataFrame, c8: pd.DataFrame, basin: str, idx: pd.DatetimeIndex):
    """Causal as-of bare share on each day in idx -> (bare_asof, age_days, src).

    Preferred: the modis module's `bare_share_asof` / `age_days` / `asof_src` columns in
    cover_basin_daily.parquet, when present. Fallback (built here, same rule): the latest
    MODIS 13Q1 composite with valid_frac >= 0.30 and tile_cover_frac >= 0.90 whose 16-day window
    (composite_start .. composite_start+15) ended at least ASOF_LAG days before t.
    age_days = t - window end.
    """
    c = cv[cv.basin == basin].set_index("date").sort_index()
    if "bare_share_asof" in c.columns:
        bare = c["bare_share_asof"].astype(float).reindex(idx)
        age = (c["age_days"].astype(float).reindex(idx) if "age_days" in c.columns
               else pd.Series(np.nan, index=idx))
        if "asof_src" in c.columns:  # source of the as-of value ('modis' / 'hls' gap-fill)
            src = ("asof_" + c["asof_src"].astype(str)).reindex(idx).fillna("asof_none").astype(object)
        else:
            src = pd.Series("asof_modis", index=idx, dtype=object)
        # beyond the end of the provided daily file: carry the last value forward, ageing it
        last = bare.dropna().index.max() if bare.notna().any() else None
        if last is not None and last < idx[-1]:
            tail = idx > last
            bare[tail] = bare[last]
            age[tail] = age[last] + (idx[tail] - last).days
            src[tail] = "asof_carried"
        return bare, age.fillna(0.0), src
    e = c8[(c8.basin == basin)].copy()
    e = e[(e.valid_frac >= 0.30) & (e.tile_cover_frac >= 0.90) & e.bare_share.notna()]
    e["avail"] = pd.to_datetime(e["composite_start"]) + pd.Timedelta(days=15 + ASOF_LAG)
    e["wend"] = pd.to_datetime(e["composite_start"]) + pd.Timedelta(days=15)
    e = e.sort_values("avail").drop_duplicates("avail", keep="last")
    e["avail"] = e["avail"].astype("datetime64[ns]")
    e["wend"] = e["wend"].astype("datetime64[ns]")
    t = pd.DataFrame({"date": pd.DatetimeIndex(idx).astype("datetime64[ns]")})
    m = pd.merge_asof(t, e[["avail", "wend", "bare_share"]], left_on="date", right_on="avail",
                      direction="backward")
    bare = pd.Series(m["bare_share"].values, index=idx, dtype=float)
    age = pd.Series((m["date"] - m["wend"]).dt.days.values, index=idx, dtype=float)
    return bare, age, pd.Series("modis_asof_m01", index=idx, dtype=object)


def load_raw(proc: Path = PROC, history: bool = False) -> pd.DataFrame:
    """One continuous daily frame per site with raw daily drivers (no rolling yet).

    history=False (v1, default): data/processed only (POWER 2015+, NWIS 2015-10+, MODIS 2015-07+, CDL 2016+).
    history=True (v2): additionally prepends the model-owned pre-2016 files written by m06_history.py
    (POWER 2008-2014, NWIS 2011-10..2015-09, MODIS 13Q1 composites 2011-07..2015-06 -> causal as-of with
    the same fallback rule, CDL 2011-2015 corn share at 240 m minus its 2016-2021 bias vs 30 m)."""
    nw = pd.read_parquet(proc / "nwis_daily.parquet")
    nw["date"] = pd.to_datetime(nw["date"])
    pw = pd.read_parquet(proc / "power_daily_basin.parquet")
    pw["date"] = pd.to_datetime(pw["date"])
    cv = pd.read_parquet(proc / "cover_basin_daily.parquet")
    cv["date"] = pd.to_datetime(cv["date"])
    c8 = pd.read_parquet(proc / "cover_basin_8day.parquet")
    cdl = pd.read_parquet(proc / "cdl_basin_year.parquet")
    if history:
        hp = pd.read_parquet(OUT / "power_daily_basin_2008_2014.parquet")
        hp["date"] = pd.to_datetime(hp["date"])
        pw = pd.concat([hp[hp.date < pw.date.min()], pw], ignore_index=True)
        hn = pd.read_parquet(OUT / "nwis_2012_2015.parquet")
        hn["date"] = pd.to_datetime(hn["date"])
        nw = pd.concat([hn[hn.date < nw.date.min()], nw], ignore_index=True)
        h8 = pd.read_parquet(OUT / "cover_basin_8day_2011_2015.parquet")
        c8_hist = pd.concat([h8, c8.assign(composite_start=pd.to_datetime(c8.composite_start))], ignore_index=True)
        hc = pd.read_parquet(OUT / "cdl_basin_year_2011_2015.parquet")
        hc = hc.assign(corn=hc.corn - hc.corn_bias_vs_30m_2016_2021)
        cdl = pd.concat([hc[hc.year < cdl.year.min()][["basin", "year", "corn"]], cdl], ignore_index=True)

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

        # ---- cover (MODIS), CAUSAL. See cover_asof() for the rules.
        asof, age, src = cover_asof(cv, c8, basin, idx)
        if history:  # days before the processed as-of series: same rule from the historical composites
            ha, hg, _ = cover_asof(cv.drop(columns=[c for c in cv.columns if c.endswith("_asof")]), c8_hist,
                                   basin, idx)
            first = asof.first_valid_index()
            pre = (idx < first) & ha.notna().values
            asof[pre], age[pre] = ha[pre], hg[pre]
            src[pre] = "asof_modis_hist"
        df["bare_asof_raw"] = asof
        df["cover_age_days"] = age
        good = asof.notna() & (age <= FRESH_AGE)
        # climatology from TRAINING years only (2016-2022), so test/live features use no future info
        clim = doy_climatology(pd.Series(idx), pd.Series(asof.where(good).values), years=(2016, 2022))
        clim_today = pd.Series(clim.reindex(idx.dayofyear).values, index=idx)
        clim_then = pd.Series(clim.reindex(pd.DatetimeIndex(idx - pd.to_timedelta(age.fillna(0).values, unit="D")).dayofyear).values,
                              index=idx)
        # stale composites (age > FRESH_AGE): keep the last observed anomaly but let it decay toward the
        # day-of-year climatology (e-folding STALE_EFOLD days). Without a composite: climatology.
        w = np.exp(-np.clip(age - FRESH_AGE, 0, None) / STALE_EFOLD)
        bare = (clim_today + (asof - clim_then) * w).where(asof.notna(), clim_today)
        src = src.where(~((age > FRESH_AGE) & asof.notna()), src + "_stale_decay")
        src[asof.isna()] = "clim_no_composite"
        df["bare"] = bare.clip(0, 1)
        df["living"] = 1.0 - df["bare"]  # living + bare = 1 over valid row-crop pixels
        df["cover_src"] = src
        # non-causal centred interpolation as delivered (diagnostics only; never a model input)
        cc = cv[cv.basin == basin].set_index("date").sort_index()
        df["bare_centred_diag"] = cc["bare_share"].astype(float).reindex(idx)

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


# ---- v2 (legacy-N) carryover features ------------------------------------------------------------
CARRY_K = [50, 150, 400, 1000]   # mm of effective drainage per e-fold of the store (grid; LOYO CV picks)
CARRY_P = 2.0                    # drainage D = P * GWETROOT**2 (rain on wet soil drains; dry soil holds it)


def carryover_features(g: pd.DataFrame, ks=CARRY_K, p=CARRY_P) -> pd.DataFrame:
    """Slow soil/groundwater N-carryover store (Option A), causal, per site (continuous daily frame):
        S_t = S_{t-1} * exp(-D_t / k) + I_t,   flush F_t = S_{t-1} * (1 - exp(-D_t / k))
        D_t = P_t * GWETROOT_t**p (mm),  I_t = corn share * spring pulse (Apr 10 - May 31, 1 unit / yr)
    Drought years drain little, so the store (unleached N) builds up and is flushed when it gets wet again.
    Spin-up: S_0 = steady state for the first 3 years' mean drainage. Columns per k: ncarry_k<k>,
    nflush30_k<k>, nflush90_k<k>. Plus prior_gs_rain = Apr-Sep rain of the most recent completed season."""
    g = g.copy()
    d = pd.to_datetime(g["date"])
    doy = d.dt.dayofyear.values
    pulse = ((doy >= 100) & (doy <= 151)).astype(float) / 52.0
    inp = g["corn_y"].values * pulse
    P = g["P"].fillna(0).values
    gw = g["gwr"].ffill().fillna(0.5).values
    D = P * gw ** p
    n3 = min(len(D), 3 * 365)
    for k in ks:
        dec = np.exp(-D / k)
        ann_d = D[:n3].mean() * 365
        S = inp[:n3].mean() * 365 / max(1 - np.exp(-ann_d / k), 1e-6) * 0.5  # mid-year steady state
        Sv, Fv = np.empty(len(D)), np.empty(len(D))
        for i in range(len(D)):
            f = S * (1 - dec[i])
            S = S * dec[i] + inp[i]
            Sv[i], Fv[i] = S, f
        g[f"ncarry_k{k}"] = Sv
        fl = pd.Series(Fv)
        g[f"nflush30_k{k}"] = fl.rolling(30, min_periods=24).sum().values
        g[f"nflush90_k{k}"] = fl.rolling(90, min_periods=72).sum().values
        bad = ~g["power_ok"].astype(bool).values
        g.loc[bad, [f"ncarry_k{k}", f"nflush30_k{k}", f"nflush90_k{k}"]] = np.nan
    gs = pd.Series(np.where((d.dt.month >= 4) & (d.dt.month <= 9), g["P"], 0.0)).groupby(d.dt.year.values).sum()
    season = np.where(d.dt.month >= 10, d.dt.year, d.dt.year - 1)
    g["prior_gs_rain"] = pd.Series(season).map(gs).values
    first_full = d.dt.year.min() + (0 if d.iloc[0].month <= 4 else 1)
    g.loc[season < first_full, "prior_gs_rain"] = np.nan
    return g


def carry_feats(k: int, use_prior_gs: bool) -> list[str]:
    return [f"ncarry_k{k}", f"nflush30_k{k}", f"nflush90_k{k}"] + (["prior_gs_rain"] if use_prior_gs else [])


def monotone_vector_v2(feats: list[str]) -> list[int]:
    pos = set(BARE_FEATS + BAREWET_FEATS + WET_FEATS)
    out = []
    for f in feats:
        if f in pos or f.startswith("ncarry_") or f.startswith("nflush"):
            out.append(1)
        elif f == "prior_gs_rain":
            out.append(-1)  # a wetter previous growing season leaves less unleached N
        else:
            out.append(0)
    return out
