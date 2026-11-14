"""Per-well groundwater state: local-linear-trend (LLT) Kalman filter + empirical-Bayes partial pooling.

Model for the winter (annual) water-level elevation h_t of well i (ft):
    y_t   = l_t + e_t,            e_t ~ N(0, r)            (measurement + winter-recovery noise)
    l_t+1 = l_t + b_t + eta_t,    eta_t ~ N(0, q_l)        (year-to-year level shocks: wet/dry years)
    b_t+1 = b_t + zeta_t,         zeta_t ~ N(0, q_s)       (slowly drifting decline rate)
Hyperparameters (r, q_l, q_s) are shared by all wells and estimated by maximum likelihood on the pooled
wells (diffuse start; the first two observations of each well are excluded from the likelihood).
The filtered state at the last year of the window gives the current level l_T and current slope b_T with
their covariance. Slopes are then partially pooled (empirical Bayes, two levels):
    b_i ~ N(mu_county, tau_w^2),  mu_county ~ N(mu_gmd, tau_c^2)
with tau's estimated by the DerSimonian-Laird method of moments.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from common import PROC, COUNTIES

KEEP_FLAGS = {"ok", "thin_or_absent_usgs2009"}   # water levels usable; base may be thin


def load_annual():
    L = pd.read_parquet(PROC / "wells_levels.parquet")
    M = pd.read_parquet(PROC / "wells_meta.parquet")
    A = L[L.is_annual & ~L.outlier_flag][["well_id", "year", "wl_elev_ft", "depth_to_water_ft"]].copy()
    A = A.merge(M[["well_id", "lon", "lat", "county_fips", "gmd", "base_elev_ft", "land_elev_ft", "sat_flag",
                   "sat_thick_2009_usgs_ft"]], on="well_id", how="left")
    A = A[A.sat_flag.isin(KEEP_FLAGS) & A.county_fips.isin(COUNTIES.keys())]
    return A, M


def to_matrix(A, y0, y1, min_obs=5, min_span=8):
    S = A[(A.year >= y0) & (A.year <= y1)]
    st = S.groupby("well_id").year.agg(["count", "min", "max"])
    keep = st[(st["count"] >= min_obs) & ((st["max"] - st["min"]) >= min_span)].index
    S = S[S.well_id.isin(keep)]
    years = np.arange(y0, y1 + 1)
    W = S.pivot_table(index="well_id", columns="year", values="wl_elev_ft", aggfunc="mean").reindex(columns=years)
    return W, years


def kalman(Y, r, ql, qs, return_states=False):
    """Vectorised LLT filter over wells (rows) x years (cols); NaN = missing. Returns loglik and final state."""
    N, T = Y.shape
    first = np.argmax(np.isfinite(Y), axis=1)
    a = np.zeros((N, 2))
    a[:, 0] = Y[np.arange(N), first]
    P = np.zeros((N, 2, 2))
    P[:, 0, 0] = 1e6
    P[:, 1, 1] = 100.0  # slope prior SD 10 ft/yr (effectively diffuse)
    nobs = np.zeros(N, int)
    ll = 0.0
    states = []
    for t in range(T):
        if t > 0:
            # predict
            a = np.column_stack([a[:, 0] + a[:, 1], a[:, 1]])
            P00 = P[:, 0, 0] + 2 * P[:, 0, 1] + P[:, 1, 1] + ql
            P01 = P[:, 0, 1] + P[:, 1, 1]
            P11 = P[:, 1, 1] + qs
            P = np.stack([np.stack([P00, P01], -1), np.stack([P01, P11], -1)], -2)
        y = Y[:, t]
        m = np.isfinite(y)
        if m.any():
            v = y[m] - a[m, 0]
            F = P[m, 0, 0] + r
            K = P[m, :, 0] / F[:, None]
            a[m] = a[m] + K * v[:, None]
            P[m] = P[m] - (K[:, :, None] * K[:, None, :]) * F[:, None, None]
            use = nobs[m] >= 2
            ll += -0.5 * np.sum((np.log(2 * np.pi * F) + v * v / F)[use])
            nobs[m] += 1
        if return_states:
            states.append((a.copy(), P.copy()))
    if return_states:
        return ll, a, P, states
    return ll, a, P


def fit_hyper(Y):
    def nll(th):
        r, ql, qs = np.exp(th)
        return -kalman(Y, r, ql, qs)[0]
    best = None
    for x0 in ([np.log(4.0), np.log(4.0), np.log(0.05)], [np.log(1.0), np.log(10.0), np.log(0.01)]):
        res = minimize(nll, x0, method="Nelder-Mead", options=dict(maxiter=400, xatol=1e-3, fatol=1e-2))
        if best is None or res.fun < best.fun:
            best = res
    r, ql, qs = np.exp(best.x)
    return dict(r=r, q_l=ql, q_s=qs, nll=best.fun)


def dersimonian_laird(b, v):
    b = np.asarray(b, float)
    v = np.asarray(v, float)
    w = 1 / v
    mu_fe = np.sum(w * b) / np.sum(w)
    Q = np.sum(w * (b - mu_fe) ** 2)
    k = len(b)
    denom = np.sum(w) - np.sum(w * w) / np.sum(w)
    tau2 = max(0.0, (Q - (k - 1)) / denom) if k > 1 and denom > 0 else 0.0
    ws = 1 / (v + tau2)
    mu = np.sum(ws * b) / np.sum(ws)
    se = math.sqrt(1 / np.sum(ws))
    return mu, se, tau2


def pool_slopes(df, bcol="b", vcol="b_var"):
    """Two-level EB: wells within county, counties within GMD. Adds b_post, b_post_var. Returns (df, county table)."""
    df = df.copy()
    # within-county heterogeneity: pooled across counties (more stable than per-county tau)
    num, den, ks = 0.0, 0.0, 0
    for c, g in df.groupby("county_fips"):
        if len(g) < 3:
            continue
        mu, se, t2 = dersimonian_laird(g[bcol], g[vcol])
        num += t2 * (len(g) - 1)
        den += len(g) - 1
    tau_w2 = num / den if den > 0 else 0.25
    rows = []
    for c, g in df.groupby("county_fips"):
        w = 1 / (g[vcol] + tau_w2)
        mu = np.sum(w * g[bcol]) / np.sum(w)
        se = math.sqrt(1 / np.sum(w))
        rows.append(dict(county_fips=c, gmd=COUNTIES[c][1], mu_raw=mu, se_raw=se, n_wells=len(g)))
    C = pd.DataFrame(rows)
    # counties within GMD
    out = []
    for gname, g in C.groupby("gmd"):
        mu_g, se_g, tau_c2 = dersimonian_laird(g.mu_raw, g.se_raw ** 2)
        for _, row in g.iterrows():
            prec = 1 / row.se_raw ** 2 + (1 / tau_c2 if tau_c2 > 0 else 1e9)
            mu_post = (row.mu_raw / row.se_raw ** 2 + (mu_g / tau_c2 if tau_c2 > 0 else mu_g * 1e9)) / prec
            out.append(dict(county_fips=row.county_fips, mu_post=mu_post, se_post=math.sqrt(1 / prec),
                            mu_gmd=mu_g, se_gmd=se_g, tau_c=math.sqrt(tau_c2)))
    C = C.merge(pd.DataFrame(out), on="county_fips")
    df = df.merge(C[["county_fips", "mu_post", "se_post"]], on="county_fips", how="left")
    prec = 1 / df[vcol] + 1 / tau_w2
    df["b_post"] = (df[bcol] / df[vcol] + df.mu_post / tau_w2) / prec
    df["b_post_var"] = 1 / prec + (df.se_post ** 2) * ((1 / tau_w2) / prec) ** 2
    df = df.drop(columns=["mu_post", "se_post"])
    C["tau_w"] = math.sqrt(tau_w2)
    return df, C


def well_states(A, window, hyper=None, min_obs=5, min_span=8, last_min=None):
    """Run the LLT filter on a window; returns per-well DataFrame (level & slope at window end) and hyper."""
    y0, y1 = window
    W, years = to_matrix(A, y0, y1, min_obs=min_obs, min_span=min_span)
    if last_min is not None:
        lastobs = W.apply(lambda r: r.last_valid_index(), axis=1)
        W = W[lastobs >= last_min]
    Y = W.values.astype(float)
    if hyper is None:
        rng = np.random.default_rng(1)
        idx = rng.choice(len(Y), size=min(800, len(Y)), replace=False)
        hyper = fit_hyper(Y[idx])
    ll, a, P = kalman(Y, hyper["r"], hyper["q_l"], hyper["q_s"])
    meta = A.drop_duplicates("well_id").set_index("well_id").loc[W.index]
    lastobs = W.apply(lambda r: r.last_valid_index(), axis=1).values
    lastval = W.apply(lambda r: r[r.last_valid_index()], axis=1).values
    df = pd.DataFrame(dict(well_id=W.index, lon=meta.lon.values, lat=meta.lat.values, county_fips=meta.county_fips.values,
                           gmd=meta.gmd.values, base_elev_ft=meta.base_elev_ft.values, sat_flag=meta.sat_flag.values,
                           level=a[:, 0], level_var=P[:, 0, 0], b=a[:, 1], b_var=P[:, 1, 1], lb_cov=P[:, 0, 1],
                           n_obs=np.isfinite(Y).sum(1), last_obs_year=lastobs, last_obs_val=lastval))
    df["decline"] = -df.b   # ft/yr, positive = falling
    return df, hyper, W


def ols_slopes(W):
    """Each well's own OLS trend over the window (baseline)."""
    yrs = W.columns.values.astype(float)
    out = []
    for wid, row in W.iterrows():
        m = np.isfinite(row.values)
        x, y = yrs[m], row.values[m]
        if m.sum() >= 3 and np.ptp(x) > 0:
            s, i = np.polyfit(x, y, 1)
        else:
            s, i = np.nan, np.nan
        out.append((wid, s, i))
    return pd.DataFrame(out, columns=["well_id", "ols_slope", "ols_int"]).set_index("well_id")


# ---------------------------------------------------------------------------------------------
# Weather adjustment. Year-to-year changes in winter levels respond to the previous growing season's
# weather (dry, hot summers -> more pumping and less recharge). We estimate, with well fixed effects,
#     dh_t = alpha_i + g_P * Panom_{t-1} + g_E * ET0anom_{t-1} + noise
# (Panom/ET0anom = Apr-Sep NASA POWER precip / FAO-56 ET0 anomaly in inches vs the county's mean over the
# climatology period: 1984-2025 for the clock; 1984..train_end-1 growing seasons in hindcast folds, so no test-period
# weather enters the trained slope),
# then remove the cumulative weather effect before the LLT filter, so the slope is a weather-normalised
# decline rate and forecasts assume average weather.
# ---------------------------------------------------------------------------------------------
def power_anomalies(clim_end=None):
    """Apr-Sep precip / ET0 anomalies vs each county's mean over growing seasons <= clim_end (all years if None).
    A level in water year t responds to growing season t-1, so a fold trained on water years <= E uses clim_end = E-1."""
    P = pd.read_parquet(PROC / "power_county_annual.parquet")
    base = P if clim_end is None else P[P.year <= clim_end]
    mp = base.groupby("county_fips").precip_gs_in.mean()
    me = base.groupby("county_fips").et0_gs_in.mean()
    P["pa"] = P.precip_gs_in - P.county_fips.map(mp)
    P["ea"] = P.et0_gs_in - P.county_fips.map(me)
    return P


def weather_coefs(A, end_year, start_year=1985, clim_end=None):
    P = power_anomalies(clim_end)
    B = A.sort_values(["well_id", "year"]).copy()
    B["dh"] = B.groupby("well_id").wl_elev_ft.diff()
    B["dy"] = B.groupby("well_id").year.diff()
    D = B[(B.dy == 1) & (B.year >= start_year) & (B.year <= end_year)].copy()
    D["py"] = D.year - 1
    D = D.merge(P[["county_fips", "year", "pa", "ea"]].rename(columns={"year": "py"}), on=["county_fips", "py"])
    cols = ["pa", "ea"]
    Xd = D[cols].values - D.groupby("well_id")[cols].transform("mean").values
    yd = D.dh.values - D.groupby("well_id").dh.transform("mean").values
    b, *_ = np.linalg.lstsq(Xd, yd, rcond=None)
    res = yd - Xd @ b
    dof = max(len(yd) - D.well_id.nunique() - 2, 1)
    cov = (res @ res / dof) * np.linalg.inv(Xd.T @ Xd)
    return dict(g_precip_ft_per_in=float(b[0]), g_et0_ft_per_in=float(b[1]),
                se=[float(math.sqrt(cov[0, 0])), float(math.sqrt(cov[1, 1]))], n_pairs=int(len(D)),
                years=[int(start_year), int(end_year)], clim_end=clim_end)


def weather_cum(coefs):
    """Cumulative weather effect per (county, water year): sum over water years s<=t of g . anom(s-1)."""
    P = power_anomalies(coefs.get("clim_end"))
    P["eff"] = coefs["g_precip_ft_per_in"] * P.pa + coefs["g_et0_ft_per_in"] * P.ea
    P["wy"] = P.year + 1
    P = P.sort_values(["county_fips", "wy"])
    P["cum"] = P.groupby("county_fips").eff.cumsum()
    return P[["county_fips", "wy", "cum"]].rename(columns={"wy": "year"})


def adjust_levels(A, coefs):
    C = weather_cum(coefs)
    B = A.merge(C, on=["county_fips", "year"], how="left")
    B["cum"] = B["cum"].fillna(0.0)
    B["wl_elev_ft"] = B.wl_elev_ft - B.cum
    return B, C


def forecast_var(level_var, lb_cov, b_var, H, hyper):
    """Variance of the level H years after the window end (LLT propagation, average weather) + obs noise."""
    P00, P01, P11 = level_var.copy(), lb_cov.copy(), b_var.copy()
    H = np.asarray(H, int)
    out = np.full_like(P00, np.nan, dtype=float)
    for k in range(0, int(H.max()) + 1):
        m = H == k
        out[m] = P00[m] + hyper["r"]
        P00, P01, P11 = P00 + 2 * P01 + P11 + hyper["q_l"], P01 + P11, P11 + hyper["q_s"]
    return out


def run_state(A, window, coefs=None, hyper=None, last_min=None, min_obs=5, min_span=8, clim_end=None):
    """Weather-adjusted LLT + EB pooling on a window. Returns (wells df, county table, hyper, coefs, W, cumtable)."""
    if coefs is None:
        coefs = weather_coefs(A, window[1], clim_end=clim_end)
    B, C = adjust_levels(A, coefs)
    df, hyper, W = well_states(B, window, hyper=hyper, min_obs=min_obs, min_span=min_span, last_min=last_min)
    cum_end = C[C.year == window[1]].set_index("county_fips").cum
    df["cum_end"] = df.county_fips.map(cum_end).fillna(0.0).values
    df["level_orig"] = df.level + df.cum_end          # filtered level at window end, original units
    df, Ct = pool_slopes(df)
    df["decline_post"] = -df.b_post
    return df, Ct, hyper, coefs, W, C
