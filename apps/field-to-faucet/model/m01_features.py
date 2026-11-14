"""m01: causal daily driver features per site -> model/out/features.parquet

Run: python3 model/m01_features.py   (from apps/field-to-faucet/)
See featlib.py for definitions. No lagged nitrate is used in the simulation features
(the `no3` / `lno3` columns are the target, kept for convenience).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import featlib as F  # noqa: E402


def main():
    F.OUT.mkdir(parents=True, exist_ok=True)
    raw = F.load_raw()
    feats = F.build_features(raw)
    feats.to_parquet(F.OUT / "features.parquet", compression="zstd", index=False)
    print(f"features.parquet: {len(feats):,} rows x {feats.shape[1]} cols")
    for site, g in feats.groupby("site"):
        obs = g["no3"].notna()
        print(f"  {site} {F.SITES[site]}: {g.date.min().date()}..{g.date.max().date()}, "
              f"no3 obs {obs.sum()}, power through {g.loc[g.power_ok, 'date'].max().date()}")
        print("    cover_src counts:", g.groupby("cover_src").size().to_dict())
        for sp in ["train", "test", "live"]:
            m = (g.split == sp) & obs
            print(f"    {sp}: n_obs={m.sum()}, days>10={int((g.loc[m, 'no3'] > 10).sum())}")


if __name__ == "__main__":
    main()
