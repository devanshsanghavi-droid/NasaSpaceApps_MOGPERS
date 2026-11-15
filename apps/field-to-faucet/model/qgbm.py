"""Monotone-constrained LightGBM quantile regression.

LightGBM's built-in `quantile` objective refuses monotone constraints (it renews leaf values after
each tree, which could break monotonicity). We therefore fit quantiles with a custom pinball-loss
objective (gradient of the check loss, unit Hessian), starting from the empirical alpha-quantile as
a constant init score. This honours `monotone_constraints`.
"""
from __future__ import annotations

import json

import lightgbm as lgb
import numpy as np

BASE_PARAMS = dict(learning_rate=0.03, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
                   lambda_l2=1.0, max_bin=127, verbose=-1, num_threads=1, seed=7,
                   monotone_constraints_method="advanced")


class QGBM:
    """prediction = init + [base model prediction] + booster(X). Tail quantiles (0.1/0.9) are boosted as
    offsets from the median model (`base`): with a unit Hessian the pinball objective moves a quantile
    by at most lr*alpha (or lr*(1-alpha)) per tree, so starting from a constant would leave the tails stuck
    near the unconditional quantile. Sum of monotone functions stays monotone."""

    def __init__(self, booster, init, feats, alpha, base=None):
        self.booster, self.init, self.feats, self.alpha, self.base = booster, float(init), list(feats), alpha, base

    def predict(self, X, num_iteration=None):
        b = self.base.predict(X) if self.base is not None else 0.0
        return self.init + b + self.booster.predict(X[self.feats], num_iteration=num_iteration)

    def save(self, path, base_file=None):
        self.booster.save_model(str(path))
        json.dump(dict(init=self.init, feats=self.feats, alpha=self.alpha, base_file=base_file),
                  open(str(path) + ".meta.json", "w"))

    @staticmethod
    def load(path):
        from pathlib import Path
        meta = json.load(open(str(path) + ".meta.json"))
        base = QGBM.load(Path(path).parent / meta["base_file"]) if meta.get("base_file") else None
        return QGBM(lgb.Booster(model_file=str(path)), meta["init"], meta["feats"], meta["alpha"], base)


def pinball_obj(alpha):
    """Pinball gradient with unit Hessian. LightGBM does not apply Dataset weights to a custom objective, so the
    row weights (if any) are applied here to both gradient and Hessian."""
    def f(preds, data):
        y = data.get_label()
        grad = np.where(y > preds, -alpha, 1.0 - alpha)
        hess = np.ones_like(grad)
        w = data.get_weight()
        if w is not None:
            grad, hess = grad * w, hess * w
        return grad, hess
    return f


def weighted_quantile(v, q, w=None):
    v = np.asarray(v, dtype=float)
    if w is None:
        return float(np.quantile(v, q))
    o = np.argsort(v)
    cw = np.cumsum(np.asarray(w, dtype=float)[o])
    return float(v[o][np.searchsorted(cw, q * cw[-1])])


def fit(X, y, feats, alpha, monotone, num_leaves=15, min_child_samples=50, n_estimators=400, seed=7,
        params=None, base=None, weight=None):
    """weight: optional per-row weights (e.g. Bayesian-bootstrap year weights). Rows are never duplicated, so
    min_child_samples keeps counting distinct days."""
    y = np.asarray(y, dtype=float)
    off = base.predict(X) if base is not None else 0.0
    init = weighted_quantile(y - off, alpha, weight)
    p = dict(BASE_PARAMS if params is None else params, objective=pinball_obj(alpha), num_leaves=num_leaves,
             min_child_samples=min_child_samples, monotone_constraints=list(monotone), seed=seed)
    ds = lgb.Dataset(X[feats], y - off - init, weight=None if weight is None else np.asarray(weight, dtype=float),
                     free_raw_data=False)
    b = lgb.train(p, ds, num_boost_round=n_estimators)
    return QGBM(b, init, feats, alpha, base)
