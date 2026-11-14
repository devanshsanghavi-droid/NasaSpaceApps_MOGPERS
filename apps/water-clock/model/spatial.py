"""Spatial interpolation: local ordinary kriging (exponential covariance) with per-observation error variance.

Water-level elevation has a strong regional gradient, so it is kriged as residuals from a quadratic trend
surface in x/y (EPSG:5070 metres) - i.e. universal kriging with a fixed polynomial drift. Decline rates are
kriged directly (ordinary kriging, local mean) with each well's posterior slope variance on the diagonal,
which makes the kriged surface a heteroscedastic Gaussian-process posterior: uncertainty grows away from
wells and toward the sill far from any data.
"""
from __future__ import annotations

import json
import math

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree

from common import PROC, to_xy


def empirical_variogram(x, y, z, maxd=80e3, nbins=16, max_pairs=400000, seed=0):
    n = len(z)
    rng = np.random.default_rng(seed)
    i = rng.integers(0, n, max_pairs)
    j = rng.integers(0, n, max_pairs)
    m = i != j
    i, j = i[m], j[m]
    d1 = np.hypot(x[i] - x[j], y[i] - y[j])
    g1 = 0.5 * (z[i] - z[j]) ** 2
    far = d1 > maxd / 4
    # all close pairs exactly (short lags matter most), random pairs for longer lags
    tree = cKDTree(np.column_stack([x, y]))
    pairs = tree.query_pairs(maxd / 4, output_type="ndarray")
    d2 = np.hypot(x[pairs[:, 0]] - x[pairs[:, 1]], y[pairs[:, 0]] - y[pairs[:, 1]])
    g2 = 0.5 * (z[pairs[:, 0]] - z[pairs[:, 1]]) ** 2
    d = np.concatenate([d1[far], d2])
    g = np.concatenate([g1[far], g2])
    edges = np.linspace(0, maxd, nbins + 1)
    idx = np.digitize(d, edges) - 1
    out = []
    for b in range(nbins):
        m = idx == b
        if m.sum() >= 30:
            out.append((d[m].mean(), g[m].mean(), m.sum()))
    return np.array(out)


def fit_variogram(ev, nugget_floor=0.0):
    h, g, n = ev[:, 0], ev[:, 1], ev[:, 2]

    def model(p, h):
        c0, c1, a = p
        return c0 + c1 * (1 - np.exp(-h / a))

    def res(p):
        return (model(p, h) - g) * np.sqrt(n) / np.maximum(g, 1e-9)

    p0 = [max(g[0] * 0.5, nugget_floor), max(g.max() - g[0] * 0.5, 1e-6), 15e3]
    r = least_squares(res, p0, bounds=([nugget_floor, 1e-9, 1e3], [np.inf, np.inf, 300e3]))
    c0, c1, a = r.x
    return dict(nugget=float(c0), psill=float(c1), range_m=float(a))


def krige(xo, yo, zo, xt, yt, vg, err_var=None, k=16, chunk=8000, include_nugget_at_target=True):
    """Local ordinary kriging. Returns (mean, variance) at targets."""
    xo = np.asarray(xo, float); yo = np.asarray(yo, float); zo = np.asarray(zo, float)
    n = len(zo)
    ev = np.zeros(n) if err_var is None else np.asarray(err_var, float)
    c0, c1, a = vg["nugget"], vg["psill"], vg["range_m"]
    tree = cKDTree(np.column_stack([xo, yo]))
    k = min(k, n)
    mean = np.empty(len(xt))
    var = np.empty(len(xt))
    for s in range(0, len(xt), chunk):
        e = min(s + chunk, len(xt))
        P = np.column_stack([xt[s:e], yt[s:e]])
        d, idx = tree.query(P, k=k)
        M = e - s
        X = xo[idx]; Y = yo[idx]
        D = np.hypot(X[:, :, None] - X[:, None, :], Y[:, :, None] - Y[:, None, :])
        C = c1 * np.exp(-D / a)
        diag = c0 + c1 + ev[idx]
        ii = np.arange(k)
        C[:, ii, ii] = diag
        A = np.ones((M, k + 1, k + 1))
        A[:, :k, :k] = C
        A[:, k, k] = 0.0
        b = np.ones((M, k + 1))
        b[:, :k] = c1 * np.exp(-d / a)
        sol = np.linalg.solve(A, b[:, :, None])[:, :, 0]
        lam, mu = sol[:, :k], sol[:, k]
        mean[s:e] = np.sum(lam * zo[idx], axis=1)
        v = c1 - np.sum(lam * b[:, :k], axis=1) - mu
        if include_nugget_at_target:
            v = v + c0
        var[s:e] = np.maximum(v, 0.0)
    return mean, var


def trend_design(x, y, x0=None, y0=None, s=1e5):
    if x0 is None:
        x0, y0 = 0.0, 0.0
    u = (np.asarray(x) - x0) / s
    v = (np.asarray(y) - y0) / s
    return np.column_stack([np.ones_like(u), u, v, u * u, u * v, v * v])


class UKriger:
    """Quadratic drift + ordinary kriging of residuals."""

    def __init__(self, x, y, z, err_var=None, nugget_floor=0.0):
        self.x0, self.y0 = float(np.mean(x)), float(np.mean(y))
        X = trend_design(x, y, self.x0, self.y0)
        self.beta, *_ = np.linalg.lstsq(X, z, rcond=None)
        self.res = z - X @ self.beta
        self.x, self.y = np.asarray(x, float), np.asarray(y, float)
        self.err = err_var
        ev = empirical_variogram(self.x, self.y, self.res)
        self.ev = ev
        self.vg = fit_variogram(ev, nugget_floor=nugget_floor)

    def predict(self, xt, yt, k=16, nugget=True):
        m, v = krige(self.x, self.y, self.res, xt, yt, self.vg, err_var=self.err, k=k, include_nugget_at_target=nugget)
        return trend_design(xt, yt, self.x0, self.y0) @ self.beta + m, v


class OKriger:
    def __init__(self, x, y, z, err_var=None):
        self.x, self.y, self.z = np.asarray(x, float), np.asarray(y, float), np.asarray(z, float)
        self.err = err_var
        self.ev = empirical_variogram(self.x, self.y, self.z)
        floor = float(np.median(err_var)) * 0.0 if err_var is not None else 0.0
        self.vg = fit_variogram(self.ev, nugget_floor=floor)
        if err_var is not None:
            # the empirical nugget contains the slope estimation error; remove its mean so it is not double counted
            self.vg["nugget"] = max(0.0, self.vg["nugget"] - float(np.mean(err_var)))

    def predict(self, xt, yt, k=16, nugget=False):
        # default: predict the smooth signal (the nugget of slope estimates is estimation noise)
        return krige(self.x, self.y, self.z, xt, yt, self.vg, err_var=self.err, k=k, include_nugget_at_target=nugget)


def load_grid():
    """Aquifer base grid (0.02 deg) -> flat arrays of cell centres inside the region with base + flags."""
    B = json.load(open(PROC / "aquifer_base.json"))
    S = json.load(open(PROC / "sat_thickness_published.json"))
    lons = np.array(B["lons"]); lats = np.array(B["lats"])
    LON, LAT = np.meshgrid(lons, lats)
    base = np.array(B["base_blend_ft"], dtype=float)
    present = np.array(B["hpa_present_2009"], dtype=object)
    present = np.where(present == None, False, present).astype(bool)  # noqa: E711
    pub = np.array(S["sat_thick_ft"], dtype=float)
    return dict(lon=LON.ravel(), lat=LAT.ravel(), base=base.ravel(), present=present.ravel(), pub2009=pub.ravel(),
                cell_deg=B["cell_deg"], base_src=B["sources"])


def base_at(lon, lat, grid=None):
    """Bilinear-ish (nearest cell) lookup of the blended base at arbitrary points."""
    B = json.load(open(PROC / "aquifer_base.json"))
    lons = np.array(B["lons"]); lats = np.array(B["lats"])
    base = np.array(B["base_blend_ft"], dtype=float)
    pres = np.array(B["hpa_present_2009"], dtype=object)
    pres = np.where(pres == None, False, pres).astype(bool)  # noqa: E711
    from scipy.interpolate import RegularGridInterpolator
    order = np.argsort(lats)
    f = RegularGridInterpolator((lats[order], lons), base[order], bounds_error=False, fill_value=np.nan)
    v = f(np.column_stack([lat, lon]))
    # fall back to nearest where bilinear hits a NaN neighbour
    fn = RegularGridInterpolator((lats[order], lons), base[order], method="nearest", bounds_error=False, fill_value=np.nan)
    vn = fn(np.column_stack([lat, lon]))
    v = np.where(np.isfinite(v), v, vn)
    fp = RegularGridInterpolator((lats[order], lons), pres[order].astype(float), method="nearest", bounds_error=False,
                                 fill_value=0.0)
    p = fp(np.column_stack([lat, lon])) > 0.5
    return v, p
