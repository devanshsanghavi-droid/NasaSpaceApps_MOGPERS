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
                   lambda_l2=1.0, max_bin=127, verbose=-1, num_threads=4, seed=7,
                   monotone_constraints_method="advanced")


class QGBM:
    def __init__(self, booster, init, feats, alpha):
        self.booster, self.init, self.feats, self.alpha = booster, float(init), list(feats), alpha

    def predict(self, X, num_iteration=None):
        return self.init + self.booster.predict(X[self.feats], num_iteration=num_iteration)

    def save(self, path):
        self.booster.save_model(str(path))
        json.dump(dict(init=self.init, feats=self.feats, alpha=self.alpha), open(str(path) + ".meta.json", "w"))

    @staticmethod
    def load(path):
        meta = json.load(open(str(path) + ".meta.json"))
        return QGBM(lgb.Booster(model_file=str(path)), meta["init"], meta["feats"], meta["alpha"])


def pinball_obj(alpha):
    def f(preds, data):
        y = data.get_label()
        grad = np.where(y > preds, -alpha, 1.0 - alpha)
        return grad, np.ones_like(grad)
    return f


def fit(X, y, feats, alpha, monotone, num_leaves=15, min_child_samples=50, n_estimators=400, seed=7,
        params=None):
    init = float(np.quantile(y, alpha))
    p = dict(BASE_PARAMS if params is None else params, objective=pinball_obj(alpha), num_leaves=num_leaves,
             min_child_samples=min_child_samples, monotone_constraints=list(monotone), seed=seed)
    ds = lgb.Dataset(X[feats], np.asarray(y) - init, free_raw_data=False)
    b = lgb.train(p, ds, num_boost_round=n_estimators)
    return QGBM(b, init, feats, alpha)
