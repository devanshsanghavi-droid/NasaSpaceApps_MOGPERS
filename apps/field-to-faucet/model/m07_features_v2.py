"""m07: v2 (legacy-N) features -> model/out/features_v2.parquet   (after m06_history.py)

Same causal features as v1 (featlib.site_features) on an extended record (POWER 2008+, NWIS 2011-10+,
MODIS 2011-07+, CDL 2011+), plus the carryover store features (featlib.carryover_features).
Run: python3 model/m07_features_v2.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402


def main():
    raw = F.load_raw(history=True)
    parts = []
    for _, g in raw.groupby("site"):
        g = F.site_features(g)
        parts.append(F.carryover_features(g))
    feats = pd.concat(parts, ignore_index=True)
    feats.to_parquet(F.OUT / "features_v2.parquet", compression="zstd", index=False)
    print(f"features_v2.parquet: {len(feats):,} rows x {feats.shape[1]} cols")
    for site, g in feats.groupby("site"):
        o = g[g.no3.notna()]
        print(f"  {site}: {g.date.min().date()}..{g.date.max().date()}; nitrate days by year "
              f"{o.groupby(o.date.dt.year).size().to_dict()}")
        print("   cover_src:", g.groupby("cover_src").size().to_dict())
        a = g.groupby(g.date.dt.year)[["ncarry_k400", "ncarry_k1000", "prior_gs_rain"]].mean().round(2)
        print("   annual mean carryover store (k=400, 1000) and prior growing-season rain:\n", a.T.to_string())


if __name__ == "__main__":
    main()
