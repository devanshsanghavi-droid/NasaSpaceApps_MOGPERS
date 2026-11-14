"""COUNTERFIELD hls module, step 3: concatenate per-scene checkpoints into data/hls_ts.parquet and write
data/raw/hls/manifest.parquet; print sanity stats by month.

One row per (field_id, date): clear observations only. If two scenes give the same point on the same date
(Landsat WRS rows 030/031 overlap, HLS2 L30 + S30 same-day, or duplicate granules), priority is
HLS2 > LC08L2/S2L2A, then L30 > S30 (L30/OLI is the HLS radiometric reference), then the first item id.
Usage: .venv/bin/python pipeline/hls_build.py
"""
import glob, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hls_common import ROOT, RAW, SCENES, SCHEMA

OUT = ROOT / "data" / "hls_ts.parquet"
START, END = pd.Timestamp("2016-01-01"), pd.Timestamp("2024-12-31")


def main():
    metas = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(SCENES / "*.json")))]
    man = pd.DataFrame(metas)
    man["date"] = pd.to_datetime(man["date"])
    man = man[(man["date"] >= START) & (man["date"] <= END)].sort_values(["date", "sensor", "item_id"])
    cols = ["item_id", "date", "sensor", "product", "collection", "cloud_cover", "n_valid", "n_fmask_clear",
            "n_clear", "n_bad_refl", "n_water"]
    man = man[cols].reset_index(drop=True)
    man.to_parquet(RAW / "manifest.parquet", index=False)
    print(f"manifest: {len(man)} scenes", man.groupby(["product", "sensor"]).size().to_dict())
    print("scenes by year/product:\n", man.groupby([man.date.dt.year, "product"]).size().unstack(fill_value=0))

    parts = []
    for iid in man["item_id"]:
        t = pq.read_table(SCENES / f"{iid}.parquet")
        if t.num_rows:
            d = t.to_pandas()
            d["_item"] = iid
            parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    n_raw = len(df)
    df["_p1"] = (df["product"] != "HLS2").astype(np.int8)
    df["_p2"] = (df["sensor"] != "L30").astype(np.int8)
    df = df.sort_values(["grid_id", "date", "_p1", "_p2", "_item"], kind="stable")
    df = df.drop_duplicates(["grid_id", "date"], keep="first")
    print(f"rows: {n_raw} raw -> {len(df)} after (field_id,date) de-dup ({n_raw-len(df)} dropped)")
    df = df.drop(columns=["_p1", "_p2", "_item"]).reset_index(drop=True)
    tbl = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    pq.write_table(tbl, OUT, compression="zstd", row_group_size=1_000_000)
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB), {len(df)} rows, {df.field_id.nunique()} points")

    # ---- sanity stats ----
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    print("\nrows by year x product:\n", df.groupby(["year", "product"]).size().unstack(fill_value=0))
    obs = df.groupby("field_id").size()
    print("\nclear obs per point: min %d / median %d / max %d; points with 0 obs: %d" %
          (obs.min(), obs.median(), obs.max(), 50850 - len(obs)))
    land = df[~df["water"]]
    q = lambda s: s.quantile([0.1, 0.5, 0.9]).round(3).tolist()
    print("\nAll land points, by month: n, NDVI p10/p50/p90, NDTI p50, BSI p50")
    for m, s in land.groupby("month"):
        print(f"  {m:2d} n={len(s):9d} ndvi={q(s.ndvi)} ndti={s.ndti.median():.3f} bsi={s.bsi.median():.3f}")
    fp = ROOT / "data" / "fields.parquet"
    if fp.exists():
        f = pd.read_parquet(fp)
        cs = []
        for yr in range(2016, 2025):
            c = f"cdl_{yr}"
            if c in f:
                sub = f.loc[f["is_field"] & f[c].isin([1, 5]), ["field_id"]].assign(year=yr, crop=f.loc[f["is_field"] & f[c].isin([1, 5]), c].map({1: "corn", 5: "soy"}))
                cs.append(sub)
        if cs:
            cs = pd.concat(cs)
            j = land.merge(cs, on=["field_id", "year"])
            print("\nCDL corn/soy fields (is_field), by month x crop: NDVI p50 [p10, p90]")
            for (m, crop), s in j.groupby(["month", "crop"]):
                print(f"  {m:2d} {crop:4s} n={len(s):8d} ndvi p50={s.ndvi.median():.3f} p10/p90={s.ndvi.quantile(.1):.3f}/{s.ndvi.quantile(.9):.3f}")
            pk = j[j.month.isin([7, 8])].groupby(["field_id", "year"]).ndvi.max()
            print(f"\n  Jul-Aug per-field-year max NDVI: median {pk.median():.3f}, p10 {pk.quantile(.1):.3f}")
    else:
        print("\n(data/fields.parquet not present yet: crop-specific stats skipped)")


if __name__ == "__main__":
    main()
