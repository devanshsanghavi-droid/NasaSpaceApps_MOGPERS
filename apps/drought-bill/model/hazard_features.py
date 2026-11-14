"""NASA POWER hazard features for the loss model, recomputed from the POWER daily cells.

Why recompute instead of only reading hazard_county_year.parquet: the 2045 bill needs the *same* features under
NEX-GDDP-CMIP6 deltas (delta method on the daily inputs), so one function computes features for observed weather and
for perturbed weather, always standardised against the OBSERVED 1991-2020 climatology of each POWER cell.
The unperturbed output reproduces the hazard module's columns (checked in build_panel.py).

Daily -> seasonal formulas follow pipeline/hazard_power.py (single-sine EDD above 30 C, gamma SPI, FAO-56 VPD,
z-scores vs 1991-2020). Extra features added here: May-June root-zone wetness (gwetroot_mj), July EDD, and anomalies
for July / August / May-June precipitation, because the 2023 IL/MO drought was mostly a spring deficit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from common import BASE0, BASE1, PROC


def sine_dd_above(tmin, tmax, thr):
    """Single-sine degree-days above thr (Baskerville & Emin 1969), degC-day per day (same as hazard_power.py)."""
    tmin = np.asarray(tmin, float)
    tmax = np.asarray(tmax, float)
    out = np.zeros_like(tmin)
    m = (tmax + tmin) / 2.0
    a = (tmax - tmin) / 2.0
    full = tmin >= thr
    out[full] = m[full] - thr
    part = (tmax > thr) & (tmin < thr)
    with np.errstate(invalid="ignore", divide="ignore"):
        th = np.arcsin(np.clip((thr - m[part]) / a[part], -1, 1))
        out[part] = ((m[part] - thr) * (np.pi / 2 - th) + a[part] * np.cos(th)) / np.pi
    return out


def es_kpa(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def load_daily():
    """POWER daily cells, May-Sep only (the features never use other months)."""
    d = pd.read_parquet(PROC / "power_daily_cells.parquet",
                        columns=["cell_id", "date", "T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "GWETROOT",
                                 "GWETTOP", "QV2M", "RH2M"])
    m = d.date.dt.month
    d = d[m.between(5, 9)].copy()
    d["year"] = d.date.dt.year.astype(int)
    d["month"] = d.date.dt.month.astype(int)
    cells = pd.read_parquet(PROC / "power_cells.parquet")[["cell_id", "elev_m"]]
    d = d.merge(cells, on="cell_id", how="left")
    return d.sort_values(["cell_id", "date"]).reset_index(drop=True)


def cell_season(d):
    """Seasonal aggregates per cell-year from daily rows (observed weather)."""
    d = d.copy()
    tmn, tmx = d.T2M_MIN.to_numpy(float), d.T2M_MAX.to_numpy(float)
    d["edd30"] = sine_dd_above(tmn, tmx, 30.0)
    p_kpa = 101.3 * ((293.0 - 0.0065 * d.elev_m.to_numpy(float)) / 293.0) ** 5.26
    q = d.QV2M.to_numpy(float) / 1000.0
    ea = q * p_kpa / (0.622 + 0.378 * q)
    d["vpd"] = np.clip((es_kpa(tmx) + es_kpa(tmn)) / 2.0 - ea, 0, None)
    m = d.month
    g = d.groupby(["cell_id", "year"])

    def s(mask, col, fn):
        gg = d[mask].groupby(["cell_id", "year"])[col]
        return gg.sum() if fn == "sum" else gg.mean()

    jja = m.between(6, 8)
    out = pd.DataFrame({
        "prcp_jja_mm": s(jja, "PRECTOTCORR", "sum"),
        "prcp_jul_mm": s(m == 7, "PRECTOTCORR", "sum"),
        "prcp_aug_mm": s(m == 8, "PRECTOTCORR", "sum"),
        "prcp_jun_mm": s(m == 6, "PRECTOTCORR", "sum"),
        "prcp_mj_mm": s(m.between(5, 6), "PRECTOTCORR", "sum"),
        "prcp_may_mm": s(m == 5, "PRECTOTCORR", "sum"),
        "prcp_sep_mm": s(m == 9, "PRECTOTCORR", "sum"),
        "edd30_jja": s(jja, "edd30", "sum"),
        "edd30_jul": s(m == 7, "edd30", "sum"),
        "tmax_jja_c": s(jja, "T2M_MAX", "mean"),
        "tmin_jja_c": s(jja, "T2M_MIN", "mean"),
        "tmax_mj_c": s(m.between(5, 6), "T2M_MAX", "mean"),
        "vpd_jja_kpa": s(jja, "vpd", "mean"),
        "gwetroot_jja": s(jja, "GWETROOT", "mean"),
        "gwetroot_jul_aug": s(m.isin([7, 8]), "GWETROOT", "mean"),
        "gwetroot_mj": s(m.between(5, 6), "GWETROOT", "mean"),
        "gwettop_jja": s(jja, "GWETTOP", "mean"),
    })
    del g
    return out.reset_index()


# ------------------------------------------------------------------ standardisation against observed base
def _gamma_params(base):
    b = base[np.isfinite(base) & (base > 0)]
    a, _, sc = stats.gamma.fit(b, floc=0)
    return a, sc


def _spi(x, a, sc):
    cdf = stats.gamma.cdf(np.where(x > 0, x, 0), a, loc=0, scale=sc)
    return stats.norm.ppf(np.clip(cdf, 1e-6, 1 - 1e-6))


def base_stats(cy_obs):
    """Per-cell 1991-2020 statistics from OBSERVED seasonal aggregates."""
    rows = []
    for cid, g in cy_obs.groupby("cell_id"):
        b = g[g.year.between(BASE0, BASE1)]
        r = {"cell_id": cid}
        for c in ["prcp_jja_mm", "prcp_jul_mm", "prcp_aug_mm", "prcp_mj_mm", "edd30_jja", "edd30_jul", "tmax_jja_c",
                  "vpd_jja_kpa", "gwetroot_jja", "gwetroot_mj", "gwetroot_jul_aug"]:
            r[c + "_mu"] = b[c].mean()
            r[c + "_sd"] = b[c].std(ddof=1)
        r["ga_jja"], r["gs_jja"] = _gamma_params(b.prcp_jja_mm.to_numpy(float))
        r["ga_mj"], r["gs_mj"] = _gamma_params(b.prcp_mj_mm.to_numpy(float))
        spi = _spi(b.prcp_jja_mm.to_numpy(float), r["ga_jja"], r["gs_jja"])
        r["negspi_mu"], r["negspi_sd"] = np.mean(-spi), np.std(-spi, ddof=1)
        r["gw_base_sorted"] = np.sort(b.gwetroot_jja.to_numpy(float))
        r["gwmj_base_sorted"] = np.sort(b.gwetroot_mj.to_numpy(float))
        rows.append(r)
    return pd.DataFrame(rows).set_index("cell_id")


def _emp_pct(x, base_sorted):
    lo = np.searchsorted(base_sorted, x, side="left")
    hi = np.searchsorted(base_sorted, x, side="right")
    return 100.0 * (lo + 0.5 * (hi - lo)) / len(base_sorted)


def standardise(cy, bs):
    """Add anomalies, SPI, percentiles, z-scores and hazard_z to seasonal aggregates `cy` (cell_id or a `cell_id`
    column must be present) using base stats `bs` (from observed weather)."""
    cy = cy.copy()
    B = bs.loc[cy.cell_id.to_numpy()]
    for c in ["prcp_jja_mm", "prcp_jul_mm", "prcp_aug_mm", "prcp_mj_mm"]:
        cy[c.replace("_mm", "_anom_pct")] = 100.0 * (cy[c].to_numpy() / B[c + "_mu"].to_numpy() - 1.0)
    cy["spi_jja"] = _spi(cy.prcp_jja_mm.to_numpy(float), B.ga_jja.to_numpy(), B.gs_jja.to_numpy())
    cy["spi_mj"] = _spi(cy.prcp_mj_mm.to_numpy(float), B.ga_mj.to_numpy(), B.gs_mj.to_numpy())
    for c, nm in [("edd30_jja", "edd30_jja_anom"), ("edd30_jul", "edd30_jul_anom"), ("tmax_jja_c", "tmax_jja_anom"),
                  ("vpd_jja_kpa", "vpd_jja_anom"), ("gwetroot_jja", "gwetroot_jja_anom"),
                  ("gwetroot_mj", "gwetroot_mj_anom"), ("gwetroot_jul_aug", "gwetroot_jul_aug_anom")]:
        cy[nm] = cy[c].to_numpy() - B[c + "_mu"].to_numpy()
    cy["gwetroot_jja_pct"] = [
        _emp_pct(x, s) for x, s in zip(cy.gwetroot_jja.to_numpy(float), B.gw_base_sorted.to_numpy())]
    cy["gwetroot_mj_pct"] = [
        _emp_pct(x, s) for x, s in zip(cy.gwetroot_mj.to_numpy(float), B.gwmj_base_sorted.to_numpy())]
    cy["z_neg_spi_jja"] = (-cy.spi_jja.to_numpy() - B.negspi_mu.to_numpy()) / B.negspi_sd.to_numpy()
    cy["z_edd30_jja"] = (cy.edd30_jja.to_numpy() - B.edd30_jja_mu.to_numpy()) / B.edd30_jja_sd.to_numpy()
    cy["z_neg_gwetroot_jja"] = -(cy.gwetroot_jja.to_numpy() - B.gwetroot_jja_mu.to_numpy()) / B.gwetroot_jja_sd.to_numpy()
    cy["hazard_z"] = cy[["z_neg_spi_jja", "z_edd30_jja", "z_neg_gwetroot_jja"]].mean(axis=1)
    # spring-inclusive composite (documented extra): adds May-June dryness to the JJA composite
    z_mj_spi = -cy.spi_mj.to_numpy()
    z_mj_gw = -(cy.gwetroot_mj.to_numpy() - B.gwetroot_mj_mu.to_numpy()) / B.gwetroot_mj_sd.to_numpy()
    cy["hazard_z_mjja"] = (cy.z_neg_spi_jja + cy.z_edd30_jja + cy.z_neg_gwetroot_jja + z_mj_spi + z_mj_gw) / 5.0
    cy["clim_prcp_jja_mm"] = B.prcp_jja_mm_mu.to_numpy()
    cy["clim_prcp_mj_mm"] = B.prcp_mj_mm_mu.to_numpy()
    cy["clim_edd30_jja"] = B.edd30_jja_mu.to_numpy()
    cy["clim_gwetroot_jja"] = B.gwetroot_jja_mu.to_numpy()
    return cy


HAZARD_FEATURES = [
    "spi_jja", "spi_mj", "prcp_jja_anom_pct", "prcp_jul_anom_pct", "prcp_aug_anom_pct", "prcp_mj_anom_pct",
    "edd30_jja", "edd30_jja_anom", "edd30_jul_anom", "tmax_jja_anom", "vpd_jja_anom",
    "gwetroot_jja_pct", "gwetroot_mj_pct", "gwetroot_jja_anom", "gwetroot_mj_anom", "gwetroot_jul_aug_anom",
    "z_neg_spi_jja", "z_edd30_jja", "z_neg_gwetroot_jja", "hazard_z", "hazard_z_mjja",
]
CLIM_FEATURES = ["clim_prcp_jja_mm", "clim_edd30_jja", "clim_gwetroot_jja"]


# ------------------------------------------------------------------ root-zone wetness emulator (for CMIP6 deltas)
EMU_TARGETS = {
    "gwetroot_jja": ["prcp_mj_frac", "prcp_jja_frac", "tmax_jja_anom"],
    "gwetroot_jul_aug": ["prcp_mj_frac", "prcp_jja_frac", "tmax_jja_anom"],
    "gwetroot_mj": ["prcp_mj_frac", "tmax_mj_anom"],
}


def fit_wetness_emulator(cy_obs, bs):
    """Within-cell (cell fixed effects) OLS of seasonal POWER root-zone wetness on fractional precipitation anomalies
    and Tmax anomalies, 1981-2024. NEX-GDDP-CMIP6 has no soil moisture, so the 2045 shift in GWETROOT is emulated
    from the projected precipitation and temperature changes with these slopes."""
    d = cy_obs[cy_obs.year <= 2024].copy()
    B = bs.loc[d.cell_id.to_numpy()]
    d["prcp_mj_frac"] = d.prcp_mj_mm.to_numpy() / B.prcp_mj_mm_mu.to_numpy() - 1
    d["prcp_jja_frac"] = d.prcp_jja_mm.to_numpy() / B.prcp_jja_mm_mu.to_numpy() - 1
    d["tmax_jja_anom"] = d.tmax_jja_c.to_numpy() - B.tmax_jja_c_mu.to_numpy()
    d["tmax_mj_anom"] = d.tmax_mj_c - d.groupby("cell_id").tmax_mj_c.transform("mean")
    res = {}
    for tgt, xs in EMU_TARGETS.items():
        cols = [tgt] + xs
        dm = d[cols] - d.groupby("cell_id")[cols].transform("mean")
        X = dm[xs].to_numpy()
        y = dm[tgt].to_numpy()
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        r2 = 1 - np.sum((y - X @ beta) ** 2) / np.sum(y ** 2)
        res[tgt] = {"x": xs, "beta": beta.tolist(), "within_r2": float(r2)}
    return res


def perturb_county_season(cs_obs, deltas, emu, daily_jja=None):
    """Future seasonal aggregates per county-year by the delta method.

    cs_obs: observed county-season table (fips, year, cell_id, seasonal aggregates).
    deltas: DataFrame indexed by fips with d_prcp_jja_pct, d_tmax_jja_c, d_tmin_jja_c, d_vpd_jja and, if present,
            d_prcp_mj_pct / d_tmax_mj_c etc. Missing month-specific deltas fall back to the JJA delta for temperature
            and to NO change for May-June precipitation (documented).
    daily_jja: dict with arrays to recompute EDD from shifted daily Tmax/Tmin (preserves the daily distribution).
    """
    f = cs_obs.copy()
    D = deltas.reindex(f.fips.to_numpy())
    dp_jja = D["d_prcp_jja_pct"].to_numpy() / 100.0
    fac = {}
    for mname in ["jun", "jul", "aug"]:
        col = f"d_prcp_{mname}_pct"
        fac[mname] = 1 + (D[col].to_numpy() / 100.0 if col in D else dp_jja)
    if "d_prcp_mj_pct" in D:
        fac_mj = 1 + D["d_prcp_mj_pct"].to_numpy() / 100.0
    elif "d_prcp_may_pct" in D and "d_prcp_jun_pct" in D:
        fac_mj = None
    else:
        fac_mj = np.ones(len(f))
    # precipitation sums scale exactly under a multiplicative monthly delta
    pj, pl, pa = (f.prcp_jun_mm.to_numpy() * fac["jun"], f.prcp_jul_mm.to_numpy() * fac["jul"],
                  f.prcp_aug_mm.to_numpy() * fac["aug"])
    if fac_mj is None:
        pmj = f.prcp_may_mm.to_numpy() * (1 + D["d_prcp_may_pct"].to_numpy() / 100) + pj
    else:
        pmj = f.prcp_mj_mm.to_numpy() * fac_mj
    new = {
        "prcp_jun_mm": pj, "prcp_jul_mm": pl, "prcp_aug_mm": pa, "prcp_jja_mm": pj + pl + pa, "prcp_mj_mm": pmj,
    }
    dtx = D["d_tmax_jja_c"].to_numpy()
    dtn = D["d_tmin_jja_c"].to_numpy() if "d_tmin_jja_c" in D else dtx
    dtx_mj = D["d_tmax_mj_c"].to_numpy() if "d_tmax_mj_c" in D else dtx
    new["tmax_jja_c"] = f.tmax_jja_c.to_numpy() + dtx
    new["tmax_mj_c"] = f.tmax_mj_c.to_numpy() + dtx_mj
    dv = D["d_vpd_jja"].to_numpy() if "d_vpd_jja" in D else np.full(len(f), np.nan)
    new["vpd_jja_kpa"] = f.vpd_jja_kpa.to_numpy() + np.nan_to_num(dv, nan=0.0)
    # EDD: shift daily Tmax/Tmin and recompute the sine degree-days
    if daily_jja is not None:
        new["edd30_jja"], new["edd30_jul"] = shifted_edd(daily_jja, f, dtx, dtn)
    else:
        d_edd = D["d_edd30_jja"].to_numpy()
        new["edd30_jja"] = f.edd30_jja.to_numpy() + d_edd
        new["edd30_jul"] = f.edd30_jul.to_numpy() + d_edd / 3
    for k, v in new.items():
        f[k] = v
    # root-zone wetness via the emulator (fractional precip change relative to that year's observed value is
    # converted to a change in fraction-of-climatology units using the observed base mean)
    base_mj = cs_obs.prcp_mj_mm.to_numpy()
    base_jja = cs_obs.prcp_jja_mm.to_numpy()
    dx = {
        "prcp_mj_frac": (pmj - base_mj) / cs_obs["clim_prcp_mj_mm"].to_numpy(),
        "prcp_jja_frac": (new["prcp_jja_mm"] - base_jja) / cs_obs["clim_prcp_jja_mm"].to_numpy(),
        "tmax_jja_anom": dtx,
        "tmax_mj_anom": dtx_mj,
    }
    for tgt, spec in emu.items():
        delta = sum(b * dx[x] for x, b in zip(spec["x"], spec["beta"]))
        f[tgt] = np.clip(cs_obs[tgt].to_numpy() + delta, 0.0, 1.0)
    return f


def daily_jja_arrays(daily):
    """Per-cell arrays of JJA daily Tmax/Tmin with year/month labels, for shifted-EDD recomputation."""
    d = daily[daily.month.between(6, 8)].sort_values(["cell_id", "date"])
    cells = d.cell_id.unique()
    n = d.groupby("cell_id").size()
    assert n.nunique() == 1
    nd = int(n.iloc[0])
    tmx = d.T2M_MAX.to_numpy(float).reshape(len(cells), nd)
    tmn = d.T2M_MIN.to_numpy(float).reshape(len(cells), nd)
    first = d[d.cell_id == cells[0]]
    return {"cells": {c: i for i, c in enumerate(cells)}, "tmax": tmx, "tmin": tmn,
            "year": first.year.to_numpy(), "month": first.month.to_numpy()}


def shifted_edd(dj, f, dtx, dtn):
    """EDD30 Jun-Aug and July for each county-year row of f after shifting daily Tmax/Tmin by the county deltas."""
    yrs = np.unique(dj["year"])
    yidx = {y: i for i, y in enumerate(yrs)}
    out_jja = np.full(len(f), np.nan)
    out_jul = np.full(len(f), np.nan)
    fips = f.fips.to_numpy()
    cell = f.cell_id.to_numpy()
    year = f.year.to_numpy()
    jul = dj["month"] == 7
    cache = {}
    for i in range(len(f)):
        key = fips[i]
        if key not in cache:
            ci = dj["cells"][cell[i]]
            e = sine_dd_above(dj["tmin"][ci] + dtn[i], dj["tmax"][ci] + dtx[i], 30.0)
            sj = np.bincount(np.searchsorted(yrs, dj["year"]), weights=e, minlength=len(yrs))
            sl = np.bincount(np.searchsorted(yrs, dj["year"][jul]), weights=e[jul], minlength=len(yrs))
            cache[key] = (sj, sl)
        sj, sl = cache[key]
        out_jja[i] = sj[yidx[year[i]]]
        out_jul[i] = sl[yidx[year[i]]]
    return out_jja, out_jul


def county_cells():
    hz = pd.read_parquet(PROC / "hazard_county_year.parquet", columns=["fips", "power_cell_id"]).drop_duplicates()
    return hz.rename(columns={"power_cell_id": "cell_id"})


def observed_county_features(return_parts=False):
    """County x year (1981-2025) observed hazard features."""
    daily = load_daily()
    cy = cell_season(daily)
    bs = base_stats(cy)
    cyz = standardise(cy, bs)
    cc = county_cells()
    feat = cc.merge(cyz, on="cell_id", how="left")
    if return_parts:
        return feat, cy, bs, daily
    return feat
