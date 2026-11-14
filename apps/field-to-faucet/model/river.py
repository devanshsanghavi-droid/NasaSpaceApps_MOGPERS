"""River nitrate model API for the scenario engine.

    import sys; sys.path.insert(0, "model")
    import river
    M = river.load_models()                       # v1 (default); river.load_models(model_version="v2") for v2
    feats = pd.read_parquet("model/out/features.parquet")   # v2: river.load_features("v2")
    g = feats[feats.site == "05484500"]
    base = river.predict(g, "05484500", M)                       # DataFrame p10, p50, p90 (mg/L)
    cf = river.predict(river.perturb_cover(g, 0.25), "05484500", M)   # 25% less bare share Oct 15-May 31

`perturb_cover` multiplies the daily causal bare-share series by (1 - frac) inside the window
(living share rises by the same amount) and recomputes every cover-derived feature (30/90/180-d means,
bare x wet sums) with the same code as m01, so lags and interactions stay consistent.
`predict_reservoir` gives the conceptual model's response for the same perturbed frame.

Caveat (see notes/model.md, sensitivity.json): the learned bare-share sensitivity is weakly identified
(historic bare-share variation is mostly seasonal / weather-driven), and the monotone constraint
guarantees direction, not magnitude. Blend with trial priors.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402
import qgbm as Q  # noqa: E402
import reservoir as RV  # noqa: E402

MODELS = F.OUT / "models"
MODELS_V2 = F.OUT / "models_v2"
OCT15_MAY31 = "oct15-may31"
FEATURES = {"v1": F.OUT / "features.parquet", "v2": F.OUT / "features_v2.parquet"}


def display_version(site: str) -> str:
    """Model version chosen for app display by the pre-registered rule (metrics.json 'display_model')."""
    try:
        return json.load(open(F.OUT / "metrics.json"))["display_model"]["sites"][site]["model"]
    except Exception:
        return "v1"


def load_features(model_version: str = "v1"):
    """Feature frame matching a model version (v2 needs the extended record + carryover columns)."""
    import pandas as _pd
    return _pd.read_parquet(FEATURES[model_version])


def load_models(models_dir: Path | None = None, model_version: str = "v1") -> dict:
    """model_version 'v1' (default, pre-registered) or 'v2' (legacy-N carryover; see notes/model.md)."""
    models_dir = Path(models_dir) if models_dir is not None else (MODELS if model_version == "v1" else MODELS_V2)
    out = {}
    for site in F.SITES:
        cfg_path = models_dir / f"config_{site}.json"
        if not cfg_path.exists():
            continue
        cfg = json.load(open(cfg_path))
        q = {a: Q.QGBM.load(models_dir / f"gbm_{site}_q{a:02d}.txt") for a in (10, 50, 90)}
        out[site] = dict(cfg=cfg, q=q, version=model_version)
    return out


def _window_mask(dates: pd.Series, months) -> np.ndarray:
    d = pd.to_datetime(dates)
    if months is None or months == OCT15_MAY31:
        md = d.dt.month * 100 + d.dt.day
        return ((md >= 1015) | (md <= 531)).values
    return d.dt.month.isin(list(months)).values


def perturb_cover(features_df: pd.DataFrame, frac: float, months=OCT15_MAY31) -> pd.DataFrame:
    """Reduce daily bare share by `frac` (0-1, relative) on days in `months` ('oct15-may31' or a list of
    month numbers) and recompute cover-derived features. Works on one or several sites (each must be a
    continuous daily series)."""
    parts = []
    for _, g in features_df.groupby("site", sort=False):
        g = g.sort_values("date").copy()
        m = _window_mask(g["date"], months)
        g.loc[m, "bare"] = g.loc[m, "bare"] * (1.0 - frac)
        parts.append(F.cover_features(g))
    return pd.concat(parts).loc[features_df.index] if len(parts) == 1 else pd.concat(parts)


def predict(features_df: pd.DataFrame, site: str, models: dict | None = None,
            model_version: str | None = None) -> pd.DataFrame:
    """GBM simulation: returns DataFrame (index aligned with features_df) with p10, p50, p90 in mg/L.
    The 80% band is the conformalized (CQR) band. Rows lacking drivers get NaN.
    `models` (from load_models) fixes the version; otherwise model_version ('v1' default, or 'v2') is loaded.
    A v2 model needs a v2 feature frame (load_features('v2'))."""
    models = models or load_models(model_version=model_version or "v1")
    mm = models[site]
    feats = mm["cfg"]["features"]
    missing = [f for f in feats if f not in features_df.columns]
    if missing:
        raise KeyError(f"features missing for {mm.get('version', 'v1')} model (use load_features('v2')?): {missing[:5]}")
    X = features_df[feats]
    ok = (features_df["rain_7"].notna() & features_df["logq"].notna() & X.notna().any(axis=1)).values
    r = np.column_stack([mm["q"][a].predict(X) for a in (10, 50, 90)])
    qhat = mm["cfg"]["cqr_qhat_log"]
    p50 = np.exp(r[:, 1])
    p10 = np.minimum(np.exp(np.minimum(r[:, 0], r[:, 1]) - qhat), p50)
    p90 = np.maximum(np.exp(np.maximum(r[:, 2], r[:, 1]) + qhat), p50)
    out = pd.DataFrame(dict(p10=p10, p50=p50, p90=p90), index=features_df.index)
    out.loc[~ok] = np.nan
    return out


def predict_reservoir(features_df: pd.DataFrame, site: str, models: dict | None = None) -> pd.Series:
    """Two-reservoir conceptual model p50 (mg/L) for one site's continuous daily frame. Spin-up uses the
    first 365 days of the frame, so pass the full history (from 2015-10-01) for best results."""
    models = models or load_models()
    cfg = models[site]["cfg"]
    g = features_df.sort_values("date")
    c = RV.predict(cfg["reservoir"], cfg["reservoir_qmed"], g)
    return pd.Series(c, index=g.index).loc[features_df.index]
