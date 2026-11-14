"""Per-county CDL acreage by crop class, 2008-2024, at the native 30 m CDL resolution (no overviews / resampling).

Inputs : data/raw/cdl/cdl_<year>_region.tif  (from nasa_cdl_fetch.py)
         Census county polygons rasterised on the same 30 m grid (pixel centre inside polygon).
Outputs: data/processed/cdl_county.parquet       county_fips, county_name, gmd, year, crop, acres, n_pixels
         data/processed/cdl_county_codes.parquet county_fips, year, cdl_code, n_pixels, acres (every raw CDL code, for remapping)
acres = n_pixels * 900 m2 / 4046.856 m2 = n_pixels * 0.22239 ac.
"""
import os
import sys

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_cdl_common import CDL_YEARS, CROP_CLASSES, PIX_AC, PROC, cdl_path, code_to_class_lut, county_raster  # noqa: E402


def main():
    cty, g = county_raster()
    nc = len(g) + 1
    lut = code_to_class_lut()
    rows, code_rows = [], []
    for y in CDL_YEARS:
        p = cdl_path(y)
        if not p.exists():
            print(f"{y}: missing {p}, skipped", flush=True)
            continue
        with rasterio.open(p) as src:
            a = src.read(1)
        assert a.shape == cty.shape
        cnt = np.zeros(nc * 256, np.int64)
        for r0 in range(0, a.shape[0], 1500):
            idx = cty[r0:r0 + 1500].astype(np.int32) * 256 + a[r0:r0 + 1500]
            cnt += np.bincount(idx.ravel(), minlength=nc * 256)
        cnt = cnt.reshape(nc, 256)
        for i, r in g.iterrows():
            c = cnt[i + 1]
            for code in np.nonzero(c)[0]:
                code_rows.append((r.fips, y, int(code), int(c[code])))
            cls = np.bincount(lut, weights=c, minlength=len(CROP_CLASSES))
            for k, name in enumerate(CROP_CLASSES):
                rows.append((r.fips, r["name"], r.gmd, y, name, int(cls[k])))
        tot = cnt[1:].sum()
        print(f"{y}: {tot*PIX_AC/1e6:.2f} M ac in counties; nodata px={cnt[1:,0].sum()}", flush=True)
    df = pd.DataFrame(rows, columns=["county_fips", "county_name", "gmd", "year", "crop", "n_pixels"])
    df["acres"] = (df.n_pixels * PIX_AC).round(1)
    df.to_parquet(PROC / "cdl_county.parquet", index=False)
    dc = pd.DataFrame(code_rows, columns=["county_fips", "year", "cdl_code", "n_pixels"])
    dc["acres"] = (dc.n_pixels * PIX_AC).round(1)
    dc.to_parquet(PROC / "cdl_county_codes.parquet", index=False)
    piv = df.groupby(["year", "crop"]).acres.sum().unstack()[CROP_CLASSES[:9]] / 1e3
    print("region totals (1000 ac):\n", piv.round(0).to_string())


if __name__ == "__main__":
    main()
