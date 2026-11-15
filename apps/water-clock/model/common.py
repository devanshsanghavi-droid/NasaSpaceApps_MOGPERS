"""Shared paths, loaders and helpers for the Water Clock model.

All inputs are the processed files written by the data modules (data/processed/). Nothing here
contains data values; constants that are not data (priors, thresholds) live in PRIORS with citations.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
PROC = APP / "data" / "processed"
CACHE = APP / "data" / "raw" / "model_cache"   # gitignored intermediate outputs
WEB = APP / "web" / "data"
CACHE.mkdir(parents=True, exist_ok=True)
WEB.mkdir(parents=True, exist_ok=True)

THRESHOLDS = [15, 30, 50]
THR_DEFAULT = 30
CAP = 100.0
RNG_SEED = 20261114

# Recent window used for the clock (water years). Winter levels Jan 2011 .. Jan 2026 = 15 years of change.
CLOCK_WINDOW = (2011, 2026)
# Hindcast: same window length, ending 2014.
HINDCAST_WINDOW = (1999, 2014)

# Literature priors. Each carries its citation; "verify" marks a citation we could not re-open from this container.
PRIORS = {
    "sy": {
        "mean": 0.15, "lo": 0.10, "hi": 0.20,
        "cite": ("Specific yield of the High Plains aquifer: USGS uses an area-weighted average of about 15% for storage-change "
                 "estimates (McGuire, USGS SIR 2017-5040 and earlier High Plains water-level reports, based on Gutentag et al. "
                 "1984, USGS PP 1400-B); range 0.10-0.20 per CONTRACTS.md / KGS. (verify exact page)"),
    },
    "recharge_in_yr": {
        "lo": 0.1, "hi": 1.5,
        "cite": ("Recharge prior for western Kansas, 0.1-1.5 in/yr. Primary sources for the central High Plains water budget: "
                 "Stanton, J.S., Qi, S.L., Ryter, D.W., et al. (2011) Selected approaches to estimate water-budget components "
                 "of the High Plains, 1940 through 1949 and 2000 through 2009. USGS SIR 2011-5183 (verify exact Kansas values); "
                 "and Hansen, C.V. (1991) Estimates of freshwater storage and potential natural recharge for principal "
                 "aquifers in Kansas. USGS WRI 87-4230 (verify). Used only as a plausibility check on the regression "
                 "intercept; the county water balance suggests net inflow in parts of GMD4/GMD1 above this range."),
    },
    "base_sd_ft": {
        "value": 22.0,
        "cite": ("1-sigma uncertainty of the aquifer base at a location: wells module found KGS depth-to-bedrock picks differ from "
                 "the USGS OFR 98-393 surface by MAD 22.6 ft, and well-level 2009 saturated thickness differs from USGS SIR 2012-5177 "
                 "by MAE 21.9 ft (notes/wells.md)."),
    },
    "butler2016": {
        "cite": ("Butler, J.J. Jr., Whittemore, D.O., Wilson, B.B., Bohling, G.C. (2016) A new approach for assessing the future "
                 "of aquifers supporting irrigated agriculture. Geophysical Research Letters 43, 2004-2010. "
                 "doi:10.1002/2016GL067879 (verify)"),
    },
}

COUNTIES = {
    "20071": ("Greeley", "GMD1"), "20203": ("Wichita", "GMD1"), "20171": ("Scott", "GMD1"), "20101": ("Lane", "GMD1"),
    "20075": ("Hamilton", "GMD3"), "20093": ("Kearny", "GMD3"), "20055": ("Finney", "GMD3"), "20069": ("Gray", "GMD3"),
    "20057": ("Ford", "GMD3"), "20187": ("Stanton", "GMD3"), "20067": ("Grant", "GMD3"), "20081": ("Haskell", "GMD3"),
    "20129": ("Morton", "GMD3"), "20189": ("Stevens", "GMD3"), "20175": ("Seward", "GMD3"), "20119": ("Meade", "GMD3"),
    "20023": ("Cheyenne", "GMD4"), "20153": ("Rawlins", "GMD4"), "20039": ("Decatur", "GMD4"), "20181": ("Sherman", "GMD4"),
    "20193": ("Thomas", "GMD4"), "20179": ("Sheridan", "GMD4"), "20199": ("Wallace", "GMD4"), "20109": ("Logan", "GMD4"),
    "20063": ("Gove", "GMD4"), "20065": ("Graham", "GMD4"),
}
GMDS = ["GMD1", "GMD3", "GMD4"]

_TRANSFORMER = None


def to_xy(lon, lat):
    """lon/lat (NAD83) -> EPSG:5070 metres."""
    global _TRANSFORMER
    if _TRANSFORMER is None:
        from pyproj import Transformer
        _TRANSFORMER = Transformer.from_crs("EPSG:4269", "EPSG:5070", always_xy=True)
    x, y = _TRANSFORMER.transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.asarray(x), np.asarray(y)


def rnd(x, nd=2):
    """Round for JSON; NaN/inf -> None."""
    if x is None:
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(xf):
        return None
    r = round(xf, nd)
    return int(r) if nd == 0 else r


def clean(obj, nd=3):
    """Recursively convert numpy types / NaN for JSON output."""
    if isinstance(obj, dict):
        return {str(k): clean(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v, nd) for v in obj]
    if isinstance(obj, (np.ndarray,)):
        return [clean(v, nd) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return rnd(obj, nd)
    return obj


def write_json(path: Path, obj, nd=3, compact=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        if compact:
            json.dump(clean(obj, nd), f, separators=(",", ":"), allow_nan=False)
        else:
            json.dump(clean(obj, nd), f, indent=1, allow_nan=False)
    return path


def load_counties_geo():
    return json.load(open(PROC / "counties.geojson"))


def county_polygons():
    import shapely.geometry as sg
    g = load_counties_geo()
    return {f["properties"]["fips"]: sg.shape(f["geometry"]) for f in g["features"]}


def county_area_acres():
    g = load_counties_geo()
    return {f["properties"]["fips"]: f["properties"]["area_km2"] * 247.105381 for f in g["features"]}


def weighted_quantile(values, weights, q):
    v = np.asarray(values, float)
    w = np.asarray(weights, float)
    m = np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not m.any():
        return np.nan
    v, w = v[m], w[m]
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w) - 0.5 * w
    cw /= w.sum()
    return float(np.interp(q, cw, v))


def ols(x, y):
    """Simple OLS slope/intercept with SE. Returns dict."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 3 or np.ptp(x) == 0:
        return dict(slope=np.nan, intercept=np.nan, se=np.nan, n=n, r2=np.nan, se_int=np.nan)
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    s2 = res @ res / max(n - 2, 1)
    cov = s2 * np.linalg.inv(X.T @ X)
    ss = ((y - y.mean()) ** 2).sum()
    return dict(slope=beta[1], intercept=beta[0], se=math.sqrt(cov[1, 1]), se_int=math.sqrt(cov[0, 0]), n=n,
                r2=1 - (res @ res) / ss if ss > 0 else np.nan, resid=res)


def trend_with_ar1(t, y):
    """OLS trend with SE inflated for lag-1 residual autocorrelation (n_eff = n(1-r1)/(1+r1))."""
    o = ols(t, y)
    if not np.isfinite(o["slope"]):
        return o
    r = o["resid"]
    r1 = np.corrcoef(r[:-1], r[1:])[0, 1] if len(r) > 3 else 0.0
    r1 = max(0.0, r1)
    n = o["n"]
    neff = max(3.0, n * (1 - r1) / (1 + r1))
    o["se_ar1"] = o["se"] * math.sqrt((n - 2) / max(neff - 2, 1))
    o["lag1"] = r1
    o["n_eff"] = neff
    return o
