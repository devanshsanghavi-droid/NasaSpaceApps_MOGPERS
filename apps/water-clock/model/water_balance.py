"""Water-balance link between reported pumping (WIMAS) and observed water-level change (wells).

Following the approach of Butler et al. (2016, GRL), for each area the annual change in mean winter water level
dWL_t (Jan t minus Jan t-1, ft) is regressed on the reported groundwater pumping of the intervening irrigation season
Q_{t-1} expressed as a depth over the area's aquifer footprint (ft = AF / acres):

    dWL_t = a + beta * Q_{t-1}/A + e_t          (physically beta = -1/Sy_app, a = net inflow / Sy_app)

Sy_app is an "apparent specific yield" on a gross-pumping basis (it absorbs irrigation return flow and lateral flow).
County slopes are combined with a physical prior beta ~ -1/Sy, Sy in 0.10-0.20 (PRIORS['sy']) by precision weighting
on 1/Sy, then partially pooled toward the GMD mean (empirical Bayes). The pumping-attributable decline used by the
scenarios is   decline_from_pumping = -beta_post * Q_recent / A   and the response coefficient per irrigated acre is
ft_per_af_ac = -beta_post * irrigated_acres / A  (ft of decline per AF/acre applied on the county's irrigated acres).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from common import PROC, COUNTIES, PRIORS, ols, county_area_acres


def county_dh(A, start=1991, end=2026):
    """County mean annual change of winter level from wells measured in consecutive years (ft)."""
    B = A.sort_values(["well_id", "year"]).copy()
    B["dh"] = B.groupby("well_id").wl_elev_ft.diff()
    B["dy"] = B.groupby("well_id").year.diff()
    D = B[(B.dy == 1) & (B.year >= start) & (B.year <= end)]
    # robust: drop extreme |dh| > 40 ft (spike screen already applied upstream; this guards pairs)
    D = D[D.dh.abs() <= 40]
    g = D.groupby(["county_fips", "year"]).dh
    out = pd.DataFrame(dict(dh=g.mean(), dh_med=g.median(), n=g.size(), sd=g.std())).reset_index()
    return out


def aquifer_fraction():
    """Share of each county's 0.02-deg grid cells where the HPA is present (USGS 2009 raster has data)."""
    import json
    import shapely.geometry as sg
    from shapely.prepared import prep
    from common import county_polygons
    from spatial import load_grid
    G = load_grid()
    polys = county_polygons()
    pts = [sg.Point(a, b) for a, b in zip(G["lon"], G["lat"])]
    frac, cell_county = {}, np.array([None] * len(pts), dtype=object)
    for f, poly in polys.items():
        pp = prep(poly)
        inside = np.array([pp.contains(p) for p in pts])
        cell_county[inside] = f
        frac[f] = float(G["present"][inside].mean()) if inside.any() else np.nan
    return frac, cell_county


def fit(A, aq_frac, years=(1991, 2026), recent=(2016, 2025)):
    W = pd.read_parquet(PROC / "wimas_county_year.parquet")
    dh = county_dh(A, *years)
    area = county_area_acres()
    sy = PRIORS["sy"]
    inv_prior_mean = 1 / sy["mean"]
    inv_prior_sd = (1 / sy["lo"] - 1 / sy["hi"]) / (2 * 1.96)  # 0.10-0.20 treated as a 95% range on 1/Sy
    rows, panel = [], []
    for f, (name, gmd) in COUNTIES.items():
        Aaq = area[f] * (aq_frac.get(f, 1.0) if np.isfinite(aq_frac.get(f, np.nan)) else 1.0)
        w = W[W.county_fips == f].set_index("year")
        d = dh[(dh.county_fips == f) & (dh.n >= 3)].set_index("year")
        q = (w.irr_af_gw / Aaq).rename("q_ft")
        dd = d.join(q.rename(lambda y: y + 1), how="inner").dropna(subset=["q_ft"])  # Jan t level vs pumping in t-1
        o = ols(dd.q_ft.values, dd.dh.values)
        qrec = w.loc[recent[0]:recent[1]].irr_af_gw.mean()
        acres_rec = w.loc[recent[0]:recent[1]].irr_acres.mean()
        panel.append(dd.assign(county_fips=f, gmd=gmd))
        rows.append(dict(county_fips=f, name=name, gmd=gmd, n_years=o["n"], beta=o["slope"], beta_se=o["se"],
                         a=o["intercept"], a_se=o["se_int"], r2=o["r2"], A_aq_acres=Aaq, aq_frac=aq_frac.get(f),
                         area_acres=area[f], q_recent_af=qrec, irr_acres_recent=acres_rec,
                         q_mean_ft=dd.q_ft.mean(), dh_mean=dd.dh.mean()))
    C = pd.DataFrame(rows)
    # inverse apparent Sy from data: invSy = -beta
    C["invsy_hat"] = -C.beta
    C["invsy_se"] = C.beta_se
    C["sy_app_hat"] = np.where(C.invsy_hat > 0, 1 / C.invsy_hat, np.nan)
    # (1) Per-county time-series slopes (Butler et al. 2016 style) are kept for diagnostics. Year-to-year pumping is
    #     largely weather-driven, so these slopes mix pumping with recharge/ET anomalies and the county footprint
    #     dilutes local pumping; they give implausible Sy_app (0.01-0.4). (2) The long-term cross-section across the
    #     26 counties (mean annual level change vs mean pumping depth, 1991-2026) is the primary estimate of 1/Sy_app;
    #     its SE is a leave-one-county-out jackknife. It is combined with the physical prior on 1/Sy.
    xs_rows = C[["county_fips", "q_mean_ft", "dh_mean"]].dropna()
    xs = ols(xs_rows.q_mean_ft.values, xs_rows.dh_mean.values)
    jk = []
    for i in range(len(xs_rows)):
        sub = xs_rows.drop(xs_rows.index[i])
        jk.append(ols(sub.q_mean_ft.values, sub.dh_mean.values)["slope"])
    jk = np.array(jk)
    n = len(jk)
    jk_se = math.sqrt((n - 1) / n * np.sum((jk - jk.mean()) ** 2))
    inv_data, inv_data_se = -xs["slope"], max(jk_se, xs["se"])
    prec = 1 / inv_data_se ** 2 + 1 / inv_prior_sd ** 2
    inv_post = (inv_data / inv_data_se ** 2 + inv_prior_mean / inv_prior_sd ** 2) / prec
    inv_post_se = math.sqrt(1 / prec)
    C["invsy_post"] = inv_post
    C["invsy_post_se"] = inv_post_se
    C["sy_post"] = 1 / inv_post
    C["data_weight"] = (1 / inv_data_se ** 2) / prec
    # county residual from the cross-section line = local net inflow (recharge + lateral) in ft/yr of level
    C["xs_resid_ft_yr"] = C.dh_mean - (xs["intercept"] + xs["slope"] * C.q_mean_ft)
    C["net_inflow_in_yr"] = (C.dh_mean + inv_post * C.q_mean_ft) * C.sy_post * 12
    C["decline_from_pumping_ft_yr"] = inv_post * C.q_recent_af / C.A_aq_acres
    C["decline_from_pumping_se"] = inv_post_se * C.q_recent_af / C.A_aq_acres
    C["ft_per_af_ac"] = inv_post * C.irr_acres_recent / C.A_aq_acres
    P = pd.concat(panel)
    # region-level pooled regression with county fixed effects (within estimator) for the notes
    Pd = P.copy()
    Pd["q_d"] = Pd.q_ft - Pd.groupby("county_fips").q_ft.transform("mean")
    Pd["dh_d"] = Pd.dh - Pd.groupby("county_fips").dh.transform("mean")
    fe = ols(Pd.q_d.values, Pd.dh_d.values)
    gmd_fits = {}
    for g in ["GMD1", "GMD3", "GMD4"]:
        # GMD aggregate series: area-weighted mean dh and total pumping over total aquifer area
        sub = P[P.gmd == g]
        cc = C[C.gmd == g].set_index("county_fips")
        sub = sub.assign(w=sub.county_fips.map(cc.A_aq_acres), qaf=sub.county_fips.map(cc.A_aq_acres) * sub.q_ft)
        agg = sub.groupby(level=0).apply(lambda s: pd.Series(dict(dh=np.average(s.dh, weights=s.w), qaf=s.qaf.sum(),
                                                                   aa=s.w.sum(), nc=len(s))))
        agg = agg[agg.nc == len(cc)]
        o = ols((agg.qaf / agg.aa).values, agg.dh.values)
        gmd_fits[g] = dict(beta=o["slope"], beta_se=o["se"], a=o["intercept"], r2=o["r2"], n=o["n"],
                           sy_app=(-1 / o["slope"]) if o["slope"] < 0 else None,
                           zero_decline_pumping_af=(-o["intercept"] / o["slope"] * cc.A_aq_acres.sum()) if o["slope"] < 0 else None,
                           recent_pumping_af=float(cc.q_recent_af.sum()))
    summary = dict(fe_within=dict(beta=fe["slope"], se=fe["se"], r2=fe["r2"], n=fe["n"],
                                  sy_app=(-1 / fe["slope"]) if fe["slope"] < 0 else None),
                   cross_section=dict(beta=xs["slope"], se=xs["se"], jackknife_se=jk_se, r2=xs["r2"], n=xs["n"],
                                      intercept=xs["intercept"], sy_app=(-1 / xs["slope"]) if xs["slope"] < 0 else None,
                                      years=list(years)),
                   posterior=dict(inv_sy=inv_post, inv_sy_se=inv_post_se, sy_app=1 / inv_post,
                                  sy_app_80=[1 / (inv_post + 1.2816 * inv_post_se), 1 / (inv_post - 1.2816 * inv_post_se)],
                                  data_weight=float((1 / inv_data_se ** 2) / prec)),
                   gmd=gmd_fits, prior=dict(sy=sy, inv_prior_mean=inv_prior_mean, inv_prior_sd=inv_prior_sd))
    return C, P, summary, dh


def regime_model(dh, coefs, windows=((1996, 2006), (2006, 2016), (2016, 2026))):
    """Decadal non-stationarity of weather-adjusted county decline rates: sigma = sqrt(floor^2 + (k*rate)^2)."""
    from wells_state import power_anomalies
    P = power_anomalies(coefs.get("clim_end"))
    P["eff"] = coefs["g_precip_ft_per_in"] * P.pa + coefs["g_et0_ft_per_in"] * P.ea
    P["year"] = P.year + 1
    D = dh.merge(P[["county_fips", "year", "eff"]], on=["county_fips", "year"], how="left")
    D["dh_adj"] = D.dh - D.eff.fillna(0)
    stats = []
    for f, g in D.groupby("county_fips"):
        r = [g[(g.year > w0) & (g.year <= w1)].dh_adj.mean() for w0, w1 in windows
             if len(g[(g.year > w0) & (g.year <= w1)]) >= 8]
        if len(r) >= 2:
            stats.append((f, abs(np.mean(r)), np.var(r, ddof=1), r))
    S = pd.DataFrame(stats, columns=["county_fips", "absmean", "var", "rates"])
    lowm = S[S.absmean < 0.5]
    floor = float(math.sqrt(lowm["var"].mean())) if len(lowm) else 0.1
    hi = S[S.absmean >= 0.5]
    k = float(math.sqrt(max(hi["var"].mean() - floor ** 2, 0) / (hi.absmean ** 2).mean())) if len(hi) else 0.3
    S["rates"] = S.rates.apply(lambda r: [round(float(x), 3) for x in r])
    return dict(floor_ft_yr=floor, k_rel=k, n_counties=int(len(S)), windows=[list(w) for w in windows],
                table=S.to_dict(orient="records"))
