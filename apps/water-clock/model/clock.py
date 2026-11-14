"""Groundwater state -> saturated thickness, decline rate and years-left (Monte Carlo) at fields, grid cells,
counties, GMDs and the region."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from common import (PROC, COUNTIES, GMDS, THRESHOLDS, CAP, RNG_SEED, PRIORS, CLOCK_WINDOW, to_xy,
                    weighted_quantile, county_polygons)
from spatial import UKriger, OKriger, load_grid, base_at

FIELD_YEARS = (2021, 2025)


def field_table():
    """WIMAS irrigation points of diversion that are groundwater-supplied and reported use > 0 in 2021-2025."""
    W = pd.read_parquet(PROC / "wimas_use.parquet",
                        columns=["pdiv_id", "year", "use", "lon", "lat", "county_fips", "source", "af_reported",
                                 "acres_irrigated", "crop_group"])
    W = W[(W.use == "IRR") & W.source.str.contains("G", na=False) & W.county_fips.isin(COUNTIES.keys())]
    R = W[(W.year >= FIELD_YEARS[0]) & (W.year <= FIELD_YEARS[1])]
    act = R[R.af_reported > 0]
    g = act.groupby("pdiv_id")
    F = pd.DataFrame(dict(lon=g.lon.first(), lat=g.lat.first(), fips=g.county_fips.first(),
                          af_yr=R.groupby("pdiv_id").af_reported.mean().reindex(g.size().index),
                          acres=act[act.acres_irrigated > 0].groupby("pdiv_id").acres_irrigated.mean(),
                          n_years_use=g.size()))
    # crop: most frequent single crop group reported 2021-2025; else CDL 250 m mode (most recent year)
    single = act[~act.crop_group.isin(["multiple/other"]) & act.crop_group.notna()]
    crop = single.groupby("pdiv_id").crop_group.agg(lambda s: s.value_counts().index[0])
    F["crop"] = crop
    F["crop_src"] = np.where(F.crop.notna(), "WIMAS", None)
    try:
        C = pd.read_parquet(PROC / "cdl_points.parquet", columns=["pdiv_id", "year", "cdl_mode_class_250m"])
        C = C[C.year >= 2020].sort_values("year").groupby("pdiv_id").cdl_mode_class_250m.last()
        mapc = {"corn": "corn", "sorghum": "sorghum", "winter_wheat": "wheat", "soybeans": "soybeans", "alfalfa": "alfalfa",
                "cotton": "cotton", "grass_pasture": "pasture", "fallow_idle": "fallow", "double_crop": "double crop"}
        cdl = C.map(lambda v: mapc.get(v, "other"))
        miss = F.crop.isna()
        F.loc[miss, "crop"] = cdl.reindex(F.index[miss]).values
        F.loc[miss & F.crop.notna(), "crop_src"] = "CDL_250m_mode"
    except FileNotFoundError:
        pass
    F["crop"] = F.crop.fillna("unknown")
    F.index.name = "id"
    return F.reset_index()


def current_levels(A, dec_kriger, year_now=CLOCK_WINDOW[1], recent=3):
    """Latest winter level per well (last `recent` water years), projected to year_now with the kriged decline.
    sat_now = wl_now - base at the well (KGS depth-to-bedrock pick where available, else blended USGS base)."""
    R = A[(A.year > year_now - recent) & (A.year <= year_now)].sort_values("year").groupby("well_id").last().reset_index()
    x, y = to_xy(R.lon.values, R.lat.values)
    d, dv = dec_kriger.predict(x, y)
    dt = year_now - R.year.values
    R["wl_now"] = R.wl_elev_ft.values - d * dt
    R["wl_var"] = 1.0 + dv * dt ** 2
    R["sat_now"] = R.wl_now - R.base_elev_ft
    R["x"], R["y"] = x, y
    return R[np.isfinite(R.sat_now)]


def regime_sigma(d, regime):
    return np.sqrt(regime["floor_ft_yr"] ** 2 + (regime["k_rel"] * np.abs(d)) ** 2)


MC_DRAWS = 10000


def years_mc(sat, sat_sd, dec, dec_sd, n=MC_DRAWS, seed=RNG_SEED, chunk=500, thresholds=THRESHOLDS):
    """p10/p50/p90 years-left at each threshold. Rising/flat -> CAP; already below -> 0.
    `dec` may be a dict {name: decline array}; then the same random draws are used for every decline vector
    (common random numbers) and the result is {name: {t: array}}, so differences between them carry no MC noise."""
    multi = isinstance(dec, dict)
    decs = dec if multi else {"_": dec}
    rng = np.random.default_rng(seed)
    outs = {k: {t: np.full((len(sat), 3), np.nan) for t in thresholds} for k in decs}
    for s in range(0, len(sat), chunk):
        e = min(s + chunk, len(sat))
        m = e - s
        zs = rng.standard_normal((m, n))
        zd = rng.standard_normal((m, n))
        S = sat[s:e, None] + sat_sd[s:e, None] * zs
        for k, dk in decs.items():
            D = dk[s:e, None] + dec_sd[s:e, None] * zd
            for t in thresholds:
                avail = S - t
                with np.errstate(divide="ignore", invalid="ignore"):
                    Y = np.where(D > 0, avail / D, CAP)
                Y = np.where(avail <= 0, 0.0, Y)
                Y = np.clip(Y, 0, CAP)
                q = np.percentile(Y, [10, 50, 90], axis=1).T
                q[~np.isfinite(sat[s:e])] = np.nan
                outs[k][t][s:e] = q
    return outs if multi else outs["_"]


def grid_cells():
    """0.02-deg cells whose centre is inside the 26 counties."""
    import shapely.geometry as sg
    from shapely.prepared import prep
    G = load_grid()
    polys = county_polygons()
    fips = np.array([None] * len(G["lon"]), dtype=object)
    pts = [sg.Point(a, b) for a, b in zip(G["lon"], G["lat"])]
    for f, poly in polys.items():
        pp = prep(poly)
        ins = np.array([pp.contains(p) for p in pts])
        fips[ins] = f
    G["fips"] = fips
    keep = fips != None  # noqa: E711
    return {k: (v[keep] if isinstance(v, np.ndarray) else v) for k, v in G.items()}


def build(A, wells, regime, base_sd=PRIORS["base_sd_ft"]["value"]):
    """Fit krigers on the current state and evaluate fields + grid."""
    xw, yw = to_xy(wells.lon.values, wells.lat.values)
    dec_k = OKriger(xw, yw, wells.decline.values)
    cur = current_levels(A, dec_k)
    # Saturated thickness is formed at the wells (wl - base at the well) and then kriged with a quadratic drift:
    # this removes the shared eastward slope of water table and base and reproduced the USGS 2009 surface better
    # (see published_check). The nugget (~ base error at wells) is replaced by the base SD at the target.
    # Only wells with sat_flag 'ok' enter the thickness kriging: at 'thin_or_absent_usgs2009' wells the base under the
    # well is doubtful (USGS 2009 maps thin/absent aquifer there, yet wl - base ranges -97..+186 ft); their water levels
    # and declines are still used.
    cs = cur[cur.sat_flag == "ok"]
    sat_k = UKriger(cs.x.values, cs.y.values, cs.sat_now.values, err_var=cs.wl_var.values)
    wl_k = UKriger(cur.x.values, cur.y.values, cur.wl_now.values, err_var=cur.wl_var.values)

    def evaluate(lon, lat, base, present):
        x, y = to_xy(lon, lat)
        d, dv = dec_k.predict(x, y)
        wl, wv = wl_k.predict(x, y)
        s, sv = sat_k.predict(x, y, nugget=False)
        sat = np.where(present & np.isfinite(base), np.maximum(s, 0.0), np.nan)
        sat_sd = np.sqrt(sv + base_sd ** 2)
        dsd = np.sqrt(dv + regime_sigma(d, regime) ** 2)
        # nearest-well distance (km) for data-quality labels
        from scipy.spatial import cKDTree
        dist, _ = cKDTree(np.column_stack([xw, yw])).query(np.column_stack([x, y]))
        return dict(wl=wl, wl_sd=np.sqrt(wv), sat=sat, sat_sd=sat_sd, decl=d, decl_sd=dsd, decl_krig_sd=np.sqrt(dv),
                    dist_km=dist / 1000)

    F = field_table()
    fb, fp = base_at(F.lon.values, F.lat.values)
    ev = evaluate(F.lon.values, F.lat.values, fb, fp)
    for k, v in ev.items():
        F[k] = v
    F["base"] = fb
    Y = years_mc(F.sat.values, F.sat_sd.values, F.decl.values, F.decl_sd.values)
    for t in THRESHOLDS:
        for j, p in enumerate(["p10", "p50", "p90"]):
            F[f"y{t}_{p}"] = Y[t][:, j]
    G = grid_cells()
    eg = evaluate(G["lon"], G["lat"], G["base"], G["present"])
    Gd = pd.DataFrame(dict(lon=G["lon"], lat=G["lat"], fips=G["fips"], base=G["base"], present=G["present"],
                           pub2009=G["pub2009"], **eg))
    YG = years_mc(Gd.sat.values, Gd.sat_sd.values, Gd.decl.values, Gd.decl_sd.values, seed=RNG_SEED + 1)
    for t in THRESHOLDS:
        for j, p in enumerate(["p10", "p50", "p90"]):
            Gd[f"y{t}_{p}"] = YG[t][:, j]
    info = dict(decline_variogram=dec_k.vg, wl_variogram=wl_k.vg, sat_variogram=sat_k.vg, wl_trend_beta=wl_k.beta.tolist(),
                n_wells_decline=int(len(wells)), n_wells_level=int(len(cur)), n_wells_sat=int(len(cs)),
                n_wells_sat_excluded_thin_flag=int(len(cur) - len(cs)), mc_draws=MC_DRAWS,
                level_years=[int(cur.year.min()), int(cur.year.max())])
    return F, Gd, info, dec_k, wl_k, cur


def published_check(A, G):
    """Krige 2009 saturated thickness at wells (same method as the clock) and compare with USGS SIR 2012-5177 2009."""
    R = A[(A.year == 2009) & (A.sat_flag == "ok")].copy()
    R["sat"] = R.wl_elev_ft - R.base_elev_ft
    R = R[np.isfinite(R.sat)]
    x, y = to_xy(R.lon.values, R.lat.values)
    gx, gy = to_xy(G.lon.values, G.lat.values)
    ks = UKriger(x, y, R.sat.values, err_var=np.ones(len(R)))
    sat09, _ = ks.predict(gx, gy)
    k = UKriger(x, y, R.wl_elev_ft.values, err_var=np.ones(len(R)))
    wl, _ = k.predict(gx, gy)
    sat09_wlroute = wl - G.base.values
    m = G.present.values & np.isfinite(G.pub2009.values) & (G.pub2009.values > 10) & np.isfinite(sat09) & np.isfinite(sat09_wlroute)
    diff = sat09[m] - G.pub2009.values[m]
    d2 = sat09_wlroute[m] - G.pub2009.values[m]
    r = np.corrcoef(sat09[m], G.pub2009.values[m])[0, 1]
    alt = dict(method="krige water-level elevation, then subtract the blended base grid", median_diff_ft=float(np.median(d2)),
               mae_ft=float(np.mean(np.abs(d2))), r=float(np.corrcoef(sat09_wlroute[m], G.pub2009.values[m])[0, 1]))
    # change 2009 -> now on the same grid (same base, so base error cancels)
    chg = G.wl.values - wl
    return dict(n_cells=int(m.sum()), median_diff_ft=float(np.median(diff)), mean_diff_ft=float(np.mean(diff)),
                mae_ft=float(np.mean(np.abs(diff))), rmse_ft=float(np.sqrt(np.mean(diff ** 2))), r=float(r),
                median_pub_ft=float(np.median(G.pub2009.values[m])), median_ours_ft=float(np.median(sat09[m])),
                n_wells_2009=int(len(R)), alternative_wl_route=alt,
                median_wl_change_2009_to_now_ft=float(np.nanmedian(chg[G.present.values])),
                note=("Our 2009 surface = 2009 winter level minus base at each well (KGS pick or USGS OFR 98-393 + KGS residual), "
                      "kriged with a quadratic drift. "
                      "USGS SIR 2012-5177 used its own water-level surface and the Gutentag et al. base and set <=10 ft cells "
                      "to 10 ft, so cells with published <=10 ft are excluded.")), sat09


def aggregate(F, wells_c, regime, wb=None, gmd_override=None):
    """County / GMD / region clocks from field-level results (weights = reported irrigated acres).
    gmd_override: {fips: gmd} to move a county for a sensitivity run."""
    F = F[np.isfinite(F.sat)].copy()
    F["w"] = F.acres.fillna(F.acres.median())
    def summarize(sub, key):
        w = sub.w.values
        res = dict(sat_thick_ft={p: weighted_quantile(sub.sat, w, q) for p, q in (("p10", .1), ("p50", .5), ("p90", .9))})
        dmean = float(np.average(sub.decl, weights=w))
        res["years_left"] = {str(t): {p: weighted_quantile(sub[f"y{t}_{p}"], w, .5) for p in ("p10", "p50", "p90")}
                             for t in THRESHOLDS}
        res["decline_est"] = dmean
        res["decline_median"] = weighted_quantile(sub.decl, w, .5)
        res["n_fields"] = int(len(sub))
        res["field_acres"] = float(sub.w.sum())
        res["median_dist_km"] = float(np.median(sub.dist_km))
        res["share_acres_lt25y"] = float(w[(sub["y30_p50"] < 25).values].sum() / w.sum())
        res["share_acres_capped"] = float(w[(sub["y30_p50"] >= CAP - 1e-9).values].sum() / w.sum())
        return res
    out = {}
    for f in COUNTIES:
        sub = F[F.fips == f]
        if len(sub):
            out[f] = summarize(sub, f)
    gm = {}
    gmd_of = {f: g for f, (n, g) in COUNTIES.items()}
    gmd_of.update(gmd_override or {})
    for g in GMDS:
        sub = F[F.fips.map(gmd_of) == g]
        gm[g] = summarize(sub, g)
    reg = summarize(F, "region")
    return out, gm, reg
