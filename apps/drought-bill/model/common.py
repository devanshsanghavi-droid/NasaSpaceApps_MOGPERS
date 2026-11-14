"""Shared paths, constants and small helpers for the Drought Bill `model` module."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "model" / "outputs"
WEB = ROOT / "web" / "data"
OUT.mkdir(parents=True, exist_ok=True)

N_THREADS = 3  # other agents share the machine
os.environ.setdefault("OMP_NUM_THREADS", str(N_THREADS))

STATES = ["IA", "NE", "KS", "MO", "IL", "SD", "MN"]
CROPS = ["corn", "soybeans", "wheat", "sorghum"]
PRINCIPAL = "principal"  # sum of the four crops (RMA `all` includes PRF rainfall-index acres, so it is not used)

TRAIN_END = 2020
TEST_YEARS = [2021, 2022, 2023, 2024]
HEADLINE_YEARS = [2022, 2023]
PROVISIONAL_YEARS = [2025]  # RMA 2025 is provisional: never used for training or testing
FIRST_YEAR = 2001
LAST_COMPLETE_YEAR = 2024
SIM_YEARS = list(range(1981, 2025))  # hazard years for the climatological simulation
BASE0, BASE1 = 1991, 2020  # climatology base used by the hazard module
RECENT = list(range(2020, 2025))  # recent window for liability/acre, subsidy share, insured acres

# Floors for keeping a county-year-crop row in the modelling panel
MIN_ACRES_CROP = 1000.0
MIN_ACRES_PRINCIPAL = 2000.0


def save_json(obj, path: Path, indent=None):
    path.parent.mkdir(parents=True, exist_ok=True)

    def conv(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):
            return [conv(x) for x in o.tolist()]
        if isinstance(o, float):
            return None if not np.isfinite(o) else o
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(x) for x in o]
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        return o

    with open(path, "w") as f:
        json.dump(conv(obj), f, indent=indent, separators=(",", ":") if indent is None else None)


def r3(x):
    """Round to 3 significant digits (None for NaN)."""
    if x is None:
        return None
    x = float(x)
    if not np.isfinite(x):
        return None
    if x == 0:
        return 0.0
    from math import floor, log10

    d = 3 - int(floor(log10(abs(x)))) - 1
    return round(x, max(d, -12))


def r2d(x):
    if x is None:
        return None
    x = float(x)
    return round(x, 2) if np.isfinite(x) else None


def wavg(x, w):
    x = np.asarray(x, float)
    w = np.asarray(w, float)
    m = np.isfinite(x) & np.isfinite(w)
    return float(np.sum(x[m] * w[m]) / np.sum(w[m])) if m.any() and np.sum(w[m]) > 0 else np.nan
