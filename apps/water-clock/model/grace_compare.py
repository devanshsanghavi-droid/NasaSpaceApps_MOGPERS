"""GRACE vs wells: regional storage anomaly from wells (Sy x mean water-level change over the region) compared with
volumetric GRACE/GRACE-FO (GFZ GravIS TWS, G3P groundwater) and the GRACE-DA groundwater percentile."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from common import PROC, COUNTIES, PRIORS, trend_with_ar1, county_area_acres

CM_PER_FT = 30.48


def well_storage_series(dh, aq_frac, y0=2002, y1=2026):
    """Region mean winter water-level anomaly (ft) chained from county mean annual changes, weighted by aquifer area."""
    area = county_area_acres()
    w = {f: area[f] * (aq_frac.get(f) if np.isfinite(aq_frac.get(f, np.nan)) else 1.0) for f in COUNTIES}
    D = dh[(dh.year > y0) & (dh.year <= y1) & (dh.n >= 3)].copy()
    D["w"] = D.county_fips.map(w)
    reg = D.groupby("year").apply(lambda s: np.average(s.dh, weights=s.w) if s.w.sum() > 0.5 * sum(w.values()) else np.nan)
    reg = reg.reindex(range(y0 + 1, y1 + 1))
    # a year with too few wells must not count as zero change: interpolate its change from neighbouring years
    n_interp = int(reg.isna().sum())
    regf = reg.interpolate(limit_direction="both")
    H = np.concatenate([[0.0], np.cumsum(regf.values)])
    years = np.arange(y0, y1 + 1)
    frac = sum(w.values()) / sum(area.values())
    return pd.Series(H, index=years), frac, reg, n_interp


def grace_winter(G, col, years):
    """Mean of months Nov(t-1)..Mar(t) (centred on the January well campaign), requires >= 2 months."""
    G = G.copy()
    G["m"] = pd.to_datetime(G["month"]).dt.month
    G["y"] = pd.to_datetime(G["month"]).dt.year
    G["wy"] = np.where(G.m >= 11, G.y + 1, G.y)
    S = G[G.m.isin([11, 12, 1, 2, 3])].groupby("wy")[col].agg(["mean", "count"])
    S = S[S["count"] >= 2]["mean"]
    return S.reindex(years)


def compare(dh, aq_frac, sy_app=None):
    """sy_app: the water-balance posterior apparent Sy; wells storage is also reported at that value."""
    H, frac, reg_dh, n_interp = well_storage_series(dh, aq_frac)
    sy = PRIORS["sy"]
    G = pd.read_parquet(PROC / "grace_region.parquet")
    years = H.index.values
    out = {"years": years.tolist(), "aquifer_area_fraction": frac, "sy": sy, "sy_app_water_balance": sy_app,
           "n_years_change_interpolated": n_interp}
    sys_ = [("mid", sy["mean"]), ("lo", sy["lo"]), ("hi", sy["hi"])]
    if sy_app is not None:
        sys_.append(("app", sy_app))
    stor = {k: H.values * s * CM_PER_FT * frac for k, s in sys_}
    out["well_storage_anom_cm"] = {k: (v - np.nanmean(v)).tolist() for k, v in stor.items()}
    out["well_wl_anom_ft"] = (H.values - H.values.mean()).tolist()
    series = {}
    for col, name in (("tws_cm", "gfz_tws_cm"), ("g3p_gws_cm", "g3p_gws_cm"), ("gws_pct", "grace_da_gws_pct")):
        if col in G:
            series[name] = grace_winter(G, col, years)
    comp = {}
    w = pd.Series(stor["mid"], index=years)
    for name, s in series.items():
        m = s.notna() & w.notna()
        if m.sum() < 6:
            continue
        r = float(np.corrcoef(w[m], s[m])[0, 1])
        dw, ds = w[m].diff(), s[m].diff()
        consecutive = pd.Series(s[m].index, index=s[m].index).diff() == 1
        mm = dw.notna() & ds.notna() & consecutive
        r_diff = float(np.corrcoef(dw[mm], ds[mm])[0, 1]) if mm.sum() > 5 else None
        comp[name] = dict(r_annual=r, r_first_difference=r_diff, n_years=int(m.sum()),
                          years=[int(s[m].index.min()), int(s[m].index.max())])
    trends = {}
    for (a, b) in ((2003, 2016), (2003, 2026), (2018, 2026)):
        t = {}
        yy = years[(years >= a) & (years <= b)]
        for k in stor:
            o = trend_with_ar1(yy, pd.Series(stor[k], index=years).loc[yy].values)
            t[f"wells_sy_{k}"] = dict(slope_cm_yr=o["slope"], se_cm_yr=o.get("se_ar1", o["se"]))
        for name in ("gfz_tws_cm", "g3p_gws_cm"):
            if name in series:
                s = series[name].loc[yy].dropna()
                if len(s) >= 5:
                    o = trend_with_ar1(s.index.values, s.values)
                    t[name] = dict(slope_cm_yr=o["slope"], se_cm_yr=o.get("se_ar1", o["se"]), n=int(len(s)),
                                   years=[int(s.index.min()), int(s.index.max())])
        if "grace_da_gws_pct" in series:
            s = series["grace_da_gws_pct"].loc[yy].dropna()
            if len(s) >= 5:
                o = trend_with_ar1(s.index.values, s.values)
                t["grace_da_gws_pct_per_yr"] = dict(slope=o["slope"], se=o.get("se_ar1", o["se"]))
        trends[f"{a}_{b}"] = t
    # monthly GRACE region trends published by the nasa module (harmonic fit, AR1-inflated) for reference
    gm = json.load(open(PROC / "grace_maps.json"))
    out.update(dict(correlation=comp, trends=trends, grace_series_winter={k: v.tolist() for k, v in series.items()},
                    nasa_module_monthly_trends=gm.get("region_trends_cm_yr")))
    return out, reg_dh
