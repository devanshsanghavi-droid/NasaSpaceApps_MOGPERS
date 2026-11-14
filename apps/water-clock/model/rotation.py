"""Rotation engine: water use, income and evidence for each strategy, per county and for the region.

Water use (net pumping, in/acre/yr) per crop = WIMAS reported application depth on single-crop irrigated
points of diversion (county-year AF/acre x 12), 2011-2025. This is the calibration target named in CONTRACTS.md
(irrigation requirement = (crop ET - effective precip)/efficiency); we use the observed applied depth directly and
use ET data only for (a) a MODIS cross-check of crop differences and (b) the climate sensitivity of the
requirement (panel regression of WIMAS AF/acre on NASA POWER Apr-Sep ET0 and precipitation, county fixed effects).

Income (USD/acre/yr, return over ERS operating costs) per crop and practice, years 2016-2025:
    yield(county, practice, year) = ALL-practice county yield(year) x ratio(practice/ALL)
ratio = county median 2000-2018 of NASS practice yield / ALL yield (state ratio when the county has none), because
NASS stopped publishing irrigated / non-irrigated county yields (corn after 2018, sorghum after 2009). Missing county
ALL yields are filled with state ALL yield x county/state median ratio. Price = Kansas marketing-year price (NASS),
cost = ERS Prairie Gateway operating cost per planted acre for that year. est = median over the 10 years, lo/hi =
10th/90th percentile over years (yield, price and cost of the same year kept together).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from common import PROC, COUNTIES, GMDS, weighted_quantile, ols

WATER_YEARS = (2011, 2025)
INCOME_YEARS = list(range(2016, 2026))
LEMA_CORN_IN = 11.0  # Sheridan-6 LEMA allocation 55 in per 5 years (see evidence; verify)

CROP_PRICE = {"corn": "corn", "sorghum": "sorghum", "wheat": "wheat", "cotton": "cotton", "soybeans": "soybeans"}


# ------------------------------------------------------------------ water
def crop_water():
    W = pd.read_parquet(PROC / "wimas_county_year.parquet")
    W = W[(W.year >= WATER_YEARS[0]) & (W.year <= WATER_YEARS[1])]
    out = {}
    gmd_of = {f: g for f, (n, g) in COUNTIES.items()}
    for crop in ("corn", "sorghum", "wheat", "cotton", "soybeans", "alfalfa"):
        ac, ap = f"acres_{crop}", f"af_per_acre_{crop}"
        if ap not in W:
            continue
        D = W[["county_fips", "year", ac, ap]].dropna()
        D = D[D[ac] >= 100]
        D["in_ac"] = D[ap] * 12
        D["gmd"] = D.county_fips.map(gmd_of)
        res = {}
        # GMD-level acre-weighted values by year (fallback)
        gm = {}
        for g, s in D.groupby("gmd"):
            yr = s.groupby("year").apply(lambda x: np.average(x.in_ac, weights=x[ac]))
            gm[g] = (yr.median(), yr.quantile(.1), yr.quantile(.9), int(s[ac].sum()))
        reg_yr = D.groupby("year").apply(lambda x: np.average(x.in_ac, weights=x[ac]))
        region = (reg_yr.median(), reg_yr.quantile(.1), reg_yr.quantile(.9))
        for f in COUNTIES:
            s = D[D.county_fips == f]
            if len(s) >= 8 and s[ac].mean() >= 300:
                res[f] = dict(est=s.in_ac.median(), lo=s.in_ac.quantile(.1), hi=s.in_ac.quantile(.9), n_years=len(s),
                              acres_mean=float(s[ac].mean()), source="county")
            elif gmd_of[f] in gm:
                e, l, h, a = gm[gmd_of[f]]
                res[f] = dict(est=e, lo=l, hi=h, n_years=int(len(s)), acres_mean=float(s[ac].mean()) if len(s) else 0.0,
                              source=f"{gmd_of[f]} acre-weighted")
            else:
                res[f] = dict(est=region[0], lo=region[1], hi=region[2], n_years=0, acres_mean=0.0, source="region")
        out[crop] = dict(county=res, gmd={g: dict(est=v[0], lo=v[1], hi=v[2], acres=v[3]) for g, v in gm.items()},
                         region=dict(est=region[0], lo=region[1], hi=region[2]), region_by_year=reg_yr.to_dict())
    return out


def climate_sensitivity():
    """Panel: county-year corn and all-crop AF/acre (in) ~ county FE + Apr-Sep ET0 (in) + Apr-Sep precip (in)."""
    W = pd.read_parquet(PROC / "wimas_county_year.parquet")
    P = pd.read_parquet(PROC / "power_county_annual.parquet")
    D = W.merge(P[["county_fips", "year", "et0_gs_in", "precip_gs_in"]], on=["county_fips", "year"])
    D = D[(D.year >= 1990) & (D.year <= 2025)]
    res = {}
    for name, col, wcol in (("corn", "af_per_acre_corn", "acres_corn"), ("all_crops", "af_per_acre", "irr_acres")):
        S = D[["county_fips", "year", col, wcol, "et0_gs_in", "precip_gs_in"]].dropna()
        S = S[S[wcol] >= 300].copy()
        S["y"] = S[col] * 12
        S["t"] = S.year - 2000
        cols = ["et0_gs_in", "precip_gs_in", "t"]
        Xd = S[cols].values - S.groupby("county_fips")[cols].transform("mean").values
        yd = S.y.values - S.groupby("county_fips").y.transform("mean").values
        b, *_ = np.linalg.lstsq(Xd, yd, rcond=None)
        r = yd - Xd @ b
        dof = len(yd) - S.county_fips.nunique() - len(cols)
        cov = (r @ r / dof) * np.linalg.inv(Xd.T @ Xd)
        res[name] = dict(in_per_in_et0=float(b[0]), in_per_in_precip=float(b[1]), trend_in_per_yr=float(b[2]),
                         se=[float(math.sqrt(cov[i, i])) for i in range(3)], r2_within=float(1 - r @ r / (yd @ yd)),
                         n=int(len(S)), years=[1990, 2025])
    return res


def modis_check():
    """MODIS MOD16A3GF pure-cell ET by crop, 2008-2024 means (relative check only; MODIS underestimates irrigated ET)."""
    M = pd.read_parquet(PROC / "modis_et_county.parquet")
    M = M[(M.year >= 2008) & (M.year <= 2024)]
    out = {}
    for c in ("corn", "sorghum", "winter_wheat", "grass_pasture", "fallow_idle"):
        col = f"et_{c}_pure_in"
        if col in M:
            out[c] = float(M[col].mean())
    out["corn_minus_sorghum_in"] = float((M.et_corn_pure_in - M.et_sorghum_pure_in).median())
    out["corn_minus_wheat_in"] = float((M.et_corn_pure_in - M.et_winter_wheat_pure_in).median())
    out["corn_minus_grass_in"] = float((M.et_corn_pure_in - M.et_grass_pasture_pure_in).median())
    return out


# ------------------------------------------------------------------ income
def yields():
    N = pd.read_parquet(PROC / "nass_county.parquet")
    st = N[N.agg_level == "STATE"]
    co = N[N.agg_level == "COUNTY"]
    out = {}
    for crop in ("corn", "sorghum", "wheat", "cotton", "soybeans"):
        sa = st[(st.crop == crop) & (st.practice == "ALL")].set_index("year")["yield"]
        ca = co[(co.crop == crop) & (co.practice == "ALL")].pivot_table(index="year", columns="county_fips", values="yield")
        ratios = {}
        for prac in ("IRRIGATED", "NON-IRRIGATED", "NON-IRRIGATED-FALLOW"):
            cp = co[(co.crop == crop) & (co.practice == prac)].pivot_table(index="year", columns="county_fips", values="yield")
            sp = st[(st.crop == crop) & (st.practice == prac)].set_index("year")["yield"]
            s_ratio = (sp / sa).dropna()
            s_ratio = s_ratio[s_ratio.index <= 2019]
            rr = {}
            for f in COUNTIES:
                if f in cp and f in ca:
                    r = (cp[f] / ca[f]).dropna()
                    r = r[r.index <= 2019]
                    if len(r) >= 3:
                        rr[f] = (float(r.median()), int(len(r)), "county")
                        continue
                if len(s_ratio):
                    rr[f] = (float(s_ratio.median()), int(len(s_ratio)), "state")
            if rr:
                ratios[prac] = rr
        # county ALL yields per year with state fill
        filled = {}
        for f in COUNTIES:
            c = ca[f] if f in ca else pd.Series(dtype=float)
            rel = (c / sa).dropna()
            k = float(rel.median()) if len(rel) >= 3 else 1.0
            ser = {}
            for y in INCOME_YEARS:
                if y in c.index and np.isfinite(c.get(y, np.nan)):
                    ser[y] = (float(c[y]), "county")
                elif y in sa.index:
                    ser[y] = (float(sa[y] * k), "state x county ratio")
            filled[f] = ser
        # variability (CV) of practice yields 2000-2018 county data
        cv = {}
        for prac in ("IRRIGATED", "NON-IRRIGATED", "NON-IRRIGATED-FALLOW", "ALL"):
            cp = co[(co.crop == crop) & (co.practice == prac) & (co.year <= 2018)]
            if len(cp) > 20:
                cvs = cp.groupby("county_fips")["yield"].agg(lambda s: s.std() / s.mean() if len(s) >= 5 else np.nan)
                cv[prac] = float(cvs.median())
        out[crop] = dict(ratios=ratios, all_filled=filled, cv=cv, unit=str(N[N.crop == crop].yield_unit.dropna().iloc[0]))
    return out


def prices_costs():
    P = pd.read_parquet(PROC / "prices.parquet").pivot(index="year", columns="crop", values="price")
    C = json.load(open(PROC / "costs.json"))
    cost = {}
    for crop, d in C["crops"].items():
        pg = d.get("Prairie Gateway", {})
        cost[crop] = {int(y): v["operating_usd_ac"] for y, v in pg.get("by_year", {}).items()}
    return P, cost


def income_series(Y, P, cost, crop, practice, f, water_frac=1.0):
    """Per-year USD/ac return over operating cost. water_frac<1 interpolates linearly between dryland and irrigated
    yields (limited irrigation; a linear water-yield assumption that is conservative versus the usual concave response)."""
    y = Y[crop]
    vals, yrs = [], []
    for yr in INCOME_YEARS:
        base = y["all_filled"][f].get(yr)
        price = P.loc[yr, CROP_PRICE[crop]] if yr in P.index else np.nan
        if crop == "cotton" and not np.isfinite(price):
            continue
        c = cost.get(crop, {}).get(yr, np.nan)
        if base is None or not np.isfinite(price) or not np.isfinite(c):
            continue
        if practice == "ALL":
            yl = base[0]
        else:
            def r(p):
                return y["ratios"].get(p, {}).get(f, (np.nan,))[0]
            if practice == "LIMITED":
                ri, rd = r("IRRIGATED"), r("NON-IRRIGATED")
                yl = base[0] * (rd + (ri - rd) * water_frac)
            else:
                yl = base[0] * r(practice)
        vals.append(yl * price - c)
        yrs.append(yr)
    out = pd.Series(vals, index=yrs, dtype=float)
    return out[np.isfinite(out)]


def rotation_mean(*series, fallow=0):
    """Mean over the rotation's crops, aligned by year (only years where every crop has a value);
    `fallow` extra zero-income years in the rotation."""
    if any(len(x) == 0 for x in series):
        return pd.Series(dtype=float)
    J = pd.concat(series, axis=1, join="inner")
    return J.sum(axis=1) / (len(series) + fallow)


def summarize(arr):
    arr = np.asarray(arr, float)
    if len(arr) == 0:
        return dict(est=np.nan, lo=np.nan, hi=np.nan)
    return dict(est=float(np.median(arr)), lo=float(np.percentile(arr, 10)), hi=float(np.percentile(arr, 90)))


STRATS = [
    dict(id="S0", name="Continuous irrigated corn (current practice)", short="Current: irrigated corn",
         rotation=["corn"], irrigation="full"),
    dict(id="S1", name="Corn-wheat-sorghum rotation with limited irrigation", short="Limited-irrigation rotation",
         rotation=["corn", "wheat", "sorghum"], irrigation="limited"),
    dict(id="S2", name="Dryland wheat-sorghum-fallow", short="Dryland rotation",
         rotation=["wheat", "sorghum", "fallow"], irrigation="none"),
    dict(id="S3", name="Irrigated grain sorghum instead of corn", short="Sorghum swap",
         rotation=["sorghum"], irrigation="full"),
    dict(id="S4", name="Irrigated cotton instead of corn (southern counties)", short="Cotton swap (south)",
         rotation=["cotton"], irrigation="full"),
]


def build(cw, Y, P, cost):
    per_county, comp = {}, {}
    for f in COUNTIES:
        wc = {k: cw[k]["county"][f] for k in ("corn", "sorghum", "wheat", "cotton")}
        corn_full = wc["corn"]["est"]
        corn_lim = min(corn_full, LEMA_CORN_IN)
        frac_lim = corn_lim / corn_full if corn_full > 0 else 1.0
        water = {
            "S0": wc["corn"]["est"],
            "S1": (corn_lim + wc["wheat"]["est"] + wc["sorghum"]["est"]) / 3,
            "S2": 0.0,
            "S3": wc["sorghum"]["est"],
            "S4": wc["cotton"]["est"],
        }
        inc = {
            "S0": income_series(Y, P, cost, "corn", "IRRIGATED", f),
            "S1": rotation_mean(income_series(Y, P, cost, "corn", "LIMITED", f, water_frac=frac_lim),
                                income_series(Y, P, cost, "wheat", "IRRIGATED", f),
                                income_series(Y, P, cost, "sorghum", "IRRIGATED", f)),
            "S2": rotation_mean(income_series(Y, P, cost, "wheat", "NON-IRRIGATED-FALLOW", f),
                                income_series(Y, P, cost, "sorghum", "NON-IRRIGATED", f), fallow=1),
            "S3": income_series(Y, P, cost, "sorghum", "IRRIGATED", f),
            "S4": income_series(Y, P, cost, "cotton", "ALL", f),
        }
        per_county[f] = {k: dict(net_pumping_in_ac=water[k], income_usd_ac=summarize(inc[k])["est"]) for k in water}
        comp[f] = dict(water=water, income={k: summarize(v) for k, v in inc.items()}, corn_limited_in=corn_lim,
                       water_sources={k: wc[k]["source"] for k in wc})
    return per_county, comp


def cotton_counties(min_years=5):
    W = pd.read_parquet(PROC / "wimas_county_year.parquet")
    W = W[(W.year >= 2011) & (W.acres_cotton.fillna(0) > 0)]
    n = W.groupby("county_fips").size()
    return sorted(n[n >= min_years].index.tolist())


def sheridan_check():
    """WIMAS reported irrigation in Sheridan County (contains most of the Sheridan-6 LEMA): before vs during the LEMA."""
    W = pd.read_parquet(PROC / "wimas_county_year.parquet")
    s = W[W.county_fips == "20179"].set_index("year")
    t = W[W.county_fips == "20193"].set_index("year")
    pre, dur = s.loc[2008:2012], s.loc[2013:2017]
    return dict(sheridan_af_2008_2012=float(pre.irr_af.mean()), sheridan_af_2013_2017=float(dur.irr_af.mean()),
                sheridan_change_pct=float((dur.irr_af.mean() / pre.irr_af.mean() - 1) * 100),
                sheridan_af_per_acre_2008_2012=float(pre.af_per_acre.mean() * 12),
                sheridan_af_per_acre_2013_2017=float(dur.af_per_acre.mean() * 12),
                thomas_change_pct=float((t.loc[2013:2017].irr_af.mean() / t.loc[2008:2012].irr_af.mean() - 1) * 100))
