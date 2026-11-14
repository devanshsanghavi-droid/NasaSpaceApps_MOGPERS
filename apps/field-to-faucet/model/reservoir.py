"""Two-reservoir conceptual nitrate model (soil-N pool + river/subsurface mixing store).

Daily, per basin, in arbitrary N units (mineralization rate fixed at 1 to remove the scale
degeneracy between the pool size and the output coefficient `a`).

  snow:      rain falls as snow when T2M <= 0; snowpack melts at 3 mm/degC/day when T2M > 0
  water in:  w_in = liquid rain + melt
  drainage:  W <- W + w_in * GWETROOT**p ;  D = W / tau_d ;  W <- W - D    (tile/subsurface drainage, mm/d)
  soil pool: S <- S + M + Fert - U - L - d*S
             M    = theta**(T-20) for T > 0 (mineralization, theta = 1.07, i.e. Q10 ~ 2), else 0
             Fert = fert * corn_share * [ (1-ff) * spring(Apr 10-May 31) + ff * fall(Nov 1-30) ]
             U    = u * living_share * GWETROOT * f(T) * S  (uptake by living cover, water- and
                                                     temperature-limited; f(T) = theta**(T-20) for T > 0, else 0)
             L    = k * S * D                            (leaching with drainage water)
  river:     R <- R + L - R/tau_r ;  O = R/tau_r
  concentration C = c0 + a * O / (Q/Qmed)**beta          (mg/L)

Fitted with scipy.optimize.least_squares on log(C) over the training years only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

PNAMES = ["fert", "ff", "u", "d", "k", "p", "tau_d", "tau_r", "c0", "a", "beta"]
LO = np.array([1.0, 0.0, 1e-4, 1e-5, 1e-5, 0.0, 1.0, 1.0, 0.05, 1e-6, 0.0])
HI = np.array([3000.0, 0.7, 0.3, 0.05, 1.0, 6.0, 120.0, 400.0, 6.0, 1e4, 1.2])
X0 = np.array([150.0, 0.25, 0.02, 0.002, 0.02, 2.0, 15.0, 30.0, 1.0, 0.5, 0.3])


def _drivers(g: pd.DataFrame, living: np.ndarray | None = None):
    d = pd.to_datetime(g["date"])
    doy = d.dt.dayofyear.values
    spring = ((doy >= 100) & (doy <= 151)).astype(float) / 52.0
    fall = ((doy >= 305) & (doy <= 334)).astype(float) / 30.0
    T = g["t2m"].ffill().fillna(0).values
    P = g["P"].fillna(0).values
    gw = g["gwr"].ffill().fillna(0.5).values
    liv = (g["living"].values if living is None else living)
    corn = g["corn_y"].values
    q = g["q_cfs"].values
    return dict(spring=spring, fall=fall, T=T, P=P, gw=gw, liv=np.nan_to_num(liv, nan=0.0), corn=corn, q=q)


def simulate(theta, dr, qmed, spin_days=365, n_spin=3):
    fert, ff, u, dd, k, p, tau_d, tau_r, c0, a, beta = theta
    T, P, gw, liv, corn = dr["T"], dr["P"], dr["gw"], dr["liv"], dr["corn"]
    n = len(T)
    M = np.where(T > 0, 1.07 ** (T - 20.0), 0.0)
    Fert = fert * corn * ((1 - ff) * dr["spring"] + ff * dr["fall"])
    snowfall = np.where(T <= 0, P, 0.0)
    rain = P - snowfall
    gwp = gw ** p
    upt = u * liv * gw * M  # M = temperature factor (also used for mineralization)
    O = np.empty(n)
    S, W, R, snow = 50.0, 10.0, 1.0, 0.0
    # spin-up: cycle through the first `spin_days` n_spin times
    order = list(range(min(spin_days, n))) * n_spin + list(range(n))
    start_main = len(order) - n
    for j, i in enumerate(order):
        melt = min(snow, 3.0 * T[i]) if T[i] > 0 else 0.0
        snow += snowfall[i] - melt
        W += (rain[i] + melt) * gwp[i]
        D = W / tau_d
        W -= D
        L = min(k * S * D, S)
        U = upt[i] * S
        S = max(S + M[i] + Fert[i] - U - L - dd * S, 0.0)
        R += L
        o = R / tau_r
        R -= o
        if j >= start_main:
            O[i] = o
    qn = np.where(np.isfinite(dr["q"]) & (dr["q"] > 0), dr["q"] / qmed, np.nan)
    return c0 + a * O / qn ** beta


NL = PNAMES                                                            # all fitted jointly
LOGP = {"fert", "u", "d", "k", "tau_d", "tau_r", "c0", "a"}           # fitted in log space


def fit(g: pd.DataFrame, train_mask: np.ndarray, seeds=4, verbose=True, max_nfev=200):
    dr = _drivers(g)
    qmed = float(np.nanmedian(g.loc[train_mask, "q_cfs"]))
    no3 = g["no3"].values
    m = train_mask & np.isfinite(no3) & (no3 > 0) & np.isfinite(dr["q"]) & (dr["q"] > 0)
    y = np.log(no3[m])
    lo = np.array([np.log(LO[j]) if k in LOGP else LO[j] for j, k in enumerate(PNAMES)])
    hi = np.array([np.log(HI[j]) if k in LOGP else HI[j] for j, k in enumerate(PNAMES)])
    ia, ic = PNAMES.index("a"), PNAMES.index("c0")

    def to_th(z):
        return np.array([np.exp(z[j]) if k in LOGP else z[j] for j, k in enumerate(PNAMES)])

    def to_z(th):
        return np.array([np.log(th[j]) if k in LOGP else th[j] for j, k in enumerate(PNAMES)])

    def resid(z):
        c = simulate(to_th(z), dr, qmed)[m]
        return np.nan_to_num(np.log(np.clip(c, 1e-3, None)) - y, nan=5.0)

    rng = np.random.default_rng(0)
    best = None
    for s in range(seeds):
        th = X0.copy()
        if s > 0:
            th = np.clip(to_th(to_z(X0) + rng.normal(0, 0.6, len(X0)) *
                               np.array([1.0 if k in LOGP else 0.2 for k in PNAMES])), LO * 1.001 + 1e-9, HI * 0.999)
        # start with the output scale matched to the observed mean (the scale is otherwise arbitrary)
        th[ia], th[ic] = 1.0, 0.0
        X = simulate(th, dr, qmed)[m]
        th[ic] = 0.3 * np.exp(y).mean()
        th[ia] = np.clip(0.7 * np.exp(y).mean() / max(np.nanmean(X), 1e-9), LO[ia] * 1.01, HI[ia] * 0.99)
        res = least_squares(resid, np.clip(to_z(th), lo + 1e-6, hi - 1e-6), bounds=(lo, hi), loss="soft_l1",
                            f_scale=0.3, max_nfev=max_nfev, x_scale="jac", diff_step=1e-3)
        if verbose:
            print(f"   reservoir seed {s}: cost {res.cost:.2f} rmse_log {np.sqrt(np.mean(res.fun ** 2)):.3f} "
                  f"nfev {res.nfev}")
        if best is None or res.cost < best.cost:
            best = res
    return dict(zip(PNAMES, map(float, to_th(best.x)))), qmed


def predict(params: dict, qmed: float, g: pd.DataFrame, living: np.ndarray | None = None) -> np.ndarray:
    th = np.array([params[k] for k in PNAMES])
    return simulate(th, _drivers(g, living), qmed)
