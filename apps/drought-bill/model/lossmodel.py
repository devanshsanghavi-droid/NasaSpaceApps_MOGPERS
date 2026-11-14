"""Loss-model library: data preparation, county encodings, candidate models (LightGBM Tweedie, spline Tweedie GLM,
county-mean baseline), fitting and prediction. Imported by fit_loss.py, simulate.py and export_web.py."""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from common import CROPS, MIN_ACRES_CROP, N_THREADS, OUT, PRINCIPAL  # noqa: E402
from hazard_features import CLIM_FEATURES, HAZARD_FEATURES  # noqa: E402

STATIC_FEATURES = ["aws0_150_mm", "aws0_100_mm", "nccpi", "irrigated_share", "irrigated_insured_share"]
CROP_CODE = {c: i for i, c in enumerate(CROPS)}
STATE_CODE = {s: i for i, s in enumerate(["IA", "NE", "KS", "MO", "IL", "SD", "MN"])}
HAZ_SMALL = ["hazard_z", "hazard_z_mjja", "spi_jja", "spi_mj", "edd30_jja_anom", "gwetroot_jja_pct",
             "gwetroot_mj_pct", "prcp_jul_anom_pct", "prcp_aug_anom_pct"]


def load_crop_panel(max_year=2024):
    p = pd.read_parquet(OUT / "panel.parquet")
    c = p[(p.crop != PRINCIPAL) & (p.year <= max_year) & (p.liability_usd > 0)].copy()
    c["lcr"] = c.lcr_drought.clip(lower=0)
    c["crop_code"] = c.crop.map(CROP_CODE)
    c["state_code"] = c.state_abbr.map(STATE_CODE)
    # weight: liability in "acre-equivalents" (liability / region-year mean liability per acre), so nominal price
    # swings do not up-weight high-price years
    lpa = c.groupby("year").apply(lambda g: g.liability_usd.sum() / g.insured_acres.sum())
    c["w"] = c.liability_usd / c.year.map(lpa)
    c["train_ok"] = c.insured_acres >= MIN_ACRES_CROP
    return c.reset_index(drop=True)


# ------------------------------------------------------------------ county encoding
def county_encoding(stats_rows, target_rows, k=5.0, col="lcr", loo_mask=None):
    """Shrunk county x crop mean of `col` (equal weight per year) toward the state x crop mean, computed from
    `stats_rows`. loo_mask (bool array over target_rows): rows that are themselves in stats_rows get their own year
    left out (prevents target leakage when encoding training rows)."""
    g = stats_rows.groupby(["fips", "crop"])[col].agg(["sum", "count"])
    sm = stats_rows.groupby(["state_abbr", "crop"])[col].mean()
    cm = stats_rows.groupby("crop")[col].mean()
    t = target_rows
    key = pd.MultiIndex.from_arrays([t.fips, t.crop])
    s = np.nan_to_num(g["sum"].reindex(key).to_numpy())
    n = np.nan_to_num(g["count"].reindex(key).to_numpy())
    if loo_mask is not None:
        lm = np.asarray(loo_mask, bool)
        s = s - np.where(lm, t[col].to_numpy(), 0.0)
        n = n - lm.astype(float)
    prior = sm.reindex(pd.MultiIndex.from_arrays([t.state_abbr, t.crop])).to_numpy()
    prior = np.where(np.isnan(prior), cm.reindex(t.crop).to_numpy(), prior)
    return (s + k * prior) / (n + k)


def add_encodings(train, test, k):
    tr = train.copy()
    te = test.copy()
    st = tr[tr.train_ok]
    tr["enc_lcr"] = county_encoding(st, tr, k=k, loo_mask=tr.train_ok.to_numpy())
    te["enc_lcr"] = county_encoding(st, te, k=k)
    return tr, te


# ------------------------------------------------------------------ candidates
def feature_list(cfg):
    f = []
    if cfg.get("hazard", "full") == "full":
        f += HAZARD_FEATURES
    elif cfg["hazard"] == "small":
        f += HAZ_SMALL
    if cfg.get("usdm"):
        f += ["dsci_jja_mean", "dsci_mjjas_mean"]
    if cfg.get("modis"):
        f += ["vci_jul_aug", "ndvi_z"]
    if cfg.get("static"):
        f += STATIC_FEATURES + CLIM_FEATURES
    if cfg.get("enc"):
        f += ["enc_lcr"]
    if cfg.get("year"):
        f += ["year"]
    if cfg.get("state"):
        f += ["state_code"]
    f += ["crop_code"]
    return f


def fit(cfg, train, seed=0):
    kind = cfg["kind"]
    tr = train[train.train_ok]
    if kind == "mean":
        return {"kind": "mean", "train": train.loc[train.train_ok, ["fips", "crop", "state_abbr", "lcr"]].copy()}
    if kind == "lgb":
        feats = feature_list(cfg)
        params = dict(objective="tweedie", tweedie_variance_power=cfg.get("tvp", 1.5), learning_rate=cfg.get("lr", 0.03),
                      num_leaves=cfg.get("leaves", 15), min_child_samples=cfg.get("mcs", 50), subsample=0.8,
                      subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, n_estimators=cfg.get("n", 400),
                      num_threads=N_THREADS, verbose=-1, random_state=seed)
        m = lgb.LGBMRegressor(**params)
        m.fit(tr[feats], tr["lcr"], sample_weight=tr["w"], categorical_feature=["crop_code"])
        return {"kind": "lgb", "model": m, "feats": feats}
    if kind == "glm":
        return fit_glm(cfg, tr)
    if kind == "ratio":
        return fit_ratio(cfg, train, seed)
    raise ValueError(kind)


def predict(cfg, fitted, df, train=None):
    kind = fitted["kind"]
    if kind == "mean":
        return county_encoding(fitted["train"], df, k=cfg.get("k", 5.0))
    if kind == "lgb":
        return np.clip(fitted["model"].predict(df[fitted["feats"]]), 0, None)
    if kind == "glm":
        return predict_glm(fitted, df)
    if kind == "ratio":
        return predict_ratio(fitted, df)
    raise ValueError(kind)


# ------------------------------------------------------------------ spline Tweedie GLM
GLM_SPLINE = ["hazard_z", "hazard_z_mjja", "spi_mj", "gwetroot_jja_pct", "edd30_jja_anom"]


def _glm_design(df, fitted=None):
    from sklearn.preprocessing import SplineTransformer

    X_parts = []
    spl = fitted["spl"] if fitted else {}
    for c in GLM_SPLINE:
        x = df[[c]].to_numpy(float)
        if c not in spl:
            spl[c] = SplineTransformer(n_knots=5, degree=3, extrapolation="linear").fit(x)
        X_parts.append(spl[c].transform(x))
    hz = df["hazard_z_mjja"].to_numpy(float)[:, None]
    stat = np.column_stack([
        np.log(df["enc_lcr"].to_numpy(float) + 1e-3),
        (df["aws0_150_mm"].to_numpy(float) - 236) / 47,
        np.nan_to_num(df["irrigated_insured_share"].to_numpy(float), nan=0.1),
    ])
    crop = np.column_stack([(df.crop_code.to_numpy() == i).astype(float) for i in range(1, 4)])
    X = np.column_stack(X_parts + [stat, stat * np.clip(hz, 0, None), crop, crop * np.clip(hz, 0, None)])
    return X, spl


def fit_glm(cfg, tr):
    from sklearn.linear_model import TweedieRegressor
    from sklearn.preprocessing import StandardScaler

    X, spl = _glm_design(tr)
    sc = StandardScaler().fit(X)
    m = TweedieRegressor(power=cfg.get("tvp", 1.5), link="log", alpha=cfg.get("alpha", 1e-3), max_iter=3000)
    m.fit(sc.transform(X), tr["lcr"], sample_weight=tr["w"])
    return {"kind": "glm", "model": m, "spl": spl, "sc": sc}


def predict_glm(fitted, df):
    X, _ = _glm_design(df, fitted)
    return np.clip(fitted["model"].predict(fitted["sc"].transform(X)), 0, None)


# ------------------------------------------------------------------ two-stage credibility (ratio) model
def fit_ratio(cfg, train, seed=0):
    """Stage 1: LightGBM Tweedie on hazard + static features (no county target info). Stage 2: county x crop
    credibility factor = (sum actual + k*mu) / (sum out-of-fold stage-1 prediction + k*mu), mu = the county's mean
    stage-1 prediction (k pseudo-years shrink the factor to 1). Out-of-fold predictions come from 5 folds of
    training YEARS, so the factor measures how a county's losses compare with what its hazard predicts."""
    base = {k: v for k, v in cfg.items() if k not in ("kind", "alpha_r", "k")}
    base["kind"] = "lgb"
    tr = train[train.train_ok].copy()
    yrs = np.sort(tr.year.unique())
    fold = {y: i % 5 for i, y in enumerate(yrs)}
    tr["fold"] = tr.year.map(fold)
    oof = np.zeros(len(tr))
    for f in range(5):
        m = tr.fold == f
        mod = fit(base, tr[~m.to_numpy()], seed=seed)
        oof[m.to_numpy()] = predict(base, mod, tr[m.to_numpy()])
    tr["oof"] = oof
    g = tr.groupby(["fips", "crop"]).agg(sa=("lcr", "sum"), sp=("oof", "sum"), n=("lcr", "size"))
    k = cfg.get("k", 5.0)
    mu = g.sp / g.n
    fac = (g.sa + k * mu) / (g.sp + k * mu)
    final = fit(base, train, seed=seed)
    return {"kind": "ratio", "base_cfg": base, "base": final, "fac": fac, "alpha": cfg.get("alpha_r", 1.0)}


def predict_ratio(fitted, df):
    p = predict(fitted["base_cfg"], fitted["base"], df)
    f = fitted["fac"].reindex(pd.MultiIndex.from_arrays([df.fips, df.crop])).to_numpy()
    f = np.where(np.isfinite(f), f, 1.0)
    return p * np.power(np.clip(f, 0.05, 20), fitted["alpha"])


# ------------------------------------------------------------------ helpers
def needs_enc(cfg):
    return cfg.get("enc") or cfg["kind"] == "glm"


def fit_predict(cfg, train, test, seed=0):
    if needs_enc(cfg):
        train, test = add_encodings(train, test, cfg.get("k", 5.0))
    f = fit(cfg, train, seed=seed)
    return predict(cfg, f, test), f


def to_principal(df, pred_col="pred"):
    """Aggregate crop-row predictions to county x year principal-crop totals."""
    d = df.assign(pred_usd=df[pred_col] * df.liability_usd)
    g = d.groupby(["fips", "state_abbr", "year"], as_index=False).agg(
        pred_usd=("pred_usd", "sum"), actual_usd=("indem_drought_usd", "sum"), liability_usd=("liability_usd", "sum"),
        insured_acres=("insured_acres", "sum"))
    return g
