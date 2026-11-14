"""Sample the 30 m USDA CDL (2008-2024) at every WIMAS point of diversion.

Input : data/processed/wimas_use.parquet (unique pdiv_id, lon, lat; produced by the pumping module)
        data/raw/cdl/cdl_<year>_region.tif (nasa_cdl_fetch.py; run it first if missing)
Output: data/processed/cdl_points.parquet  pdiv_id, year, cdl_code, cdl_class, cdl_name,
        plus cdl_mode_code_250m / cdl_mode_class_250m / mode_frac_250m = most common CDL code within a 250 m radius disk
        (17x17 30 m window, circular mask; the WIMAS location is the well/point of diversion, which is often at a
        field edge or corner, so the neighbourhood mode is usually a better guess of the irrigated field's crop).
Points outside the CDL region window get NaN. lon/lat are not repeated here (join on pdiv_id to wimas_use.parquet).
Usage : python3 pipeline/nasa_cdl_points.py
"""
import os
import sys

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_cdl_common import CDL_YEARS, CROP_CLASSES, PROC, cdl_path, code_to_class_lut  # noqa: E402

R_PIX = 8  # 8 px * 30 m ~ 250 m radius
NAMES = {1: "Corn", 2: "Cotton", 4: "Sorghum", 5: "Soybeans", 6: "Sunflower", 21: "Barley", 23: "Spring Wheat",
         24: "Winter Wheat", 26: "Dbl Crop WinWht/Soybeans", 27: "Rye", 28: "Oats", 29: "Millet", 31: "Canola",
         36: "Alfalfa", 37: "Other Hay/Non Alfalfa", 41: "Sugarbeets", 42: "Dry Beans", 43: "Potatoes", 44: "Other Crops",
         53: "Peas", 58: "Clover/Wildflowers", 59: "Sod/Grass Seed", 61: "Fallow/Idle Cropland", 62: "Pasture/Grass",
         63: "Forest", 64: "Shrubland", 111: "Open Water", 121: "Developed/Open Space", 122: "Developed/Low Intensity",
         123: "Developed/Med Intensity", 124: "Developed/High Intensity", 131: "Barren", 141: "Deciduous Forest",
         152: "Shrubland", 171: "Grassland Herbaceous", 176: "Grassland/Pasture", 181: "Pasture/Hay",
         190: "Woody Wetlands", 195: "Herbaceous Wetlands", 205: "Triticale", 225: "Dbl Crop WinWht/Corn",
         236: "Dbl Crop WinWht/Sorghum", 238: "Dbl Crop WinWht/Cotton"}


def main():
    src_p = PROC / "wimas_use.parquet"
    if not src_p.exists():
        sys.exit(f"missing {src_p} (pumping module output) - run pipeline/pumping_*.py first")
    w = pd.read_parquet(src_p, columns=["pdiv_id", "lon", "lat"]).dropna().drop_duplicates("pdiv_id")
    print(f"{len(w)} unique points of diversion", flush=True)
    x, y = Transformer.from_crs(4326, 5070, always_xy=True).transform(w.lon.values, w.lat.values)
    lut = code_to_class_lut()
    yy, xx = np.mgrid[-R_PIX:R_PIX + 1, -R_PIX:R_PIX + 1]
    disk = (yy ** 2 + xx ** 2) <= R_PIX ** 2
    out = []
    for yr in CDL_YEARS:
        p = cdl_path(yr)
        if not p.exists():
            print(f"{yr}: missing {p} - run nasa_cdl_fetch.py", flush=True)
            continue
        with rasterio.open(p) as src:
            a = src.read(1)
            c, r = ~src.transform * (x, y)
        r = np.floor(r).astype(int)
        c = np.floor(c).astype(int)
        ok = (r >= R_PIX) & (r < a.shape[0] - R_PIX) & (c >= R_PIX) & (c < a.shape[1] - R_PIX)
        code = np.full(len(w), -1, int)
        code[ok] = a[r[ok], c[ok]]
        mode = np.full(len(w), -1, int)
        frac = np.full(len(w), np.nan)
        for i in np.nonzero(ok)[0]:
            win = a[r[i] - R_PIX:r[i] + R_PIX + 1, c[i] - R_PIX:c[i] + R_PIX + 1][disk]
            bc = np.bincount(win, minlength=256)
            bc[0] = 0
            mode[i] = bc.argmax()
            frac[i] = bc.max() / disk.sum()
        out.append(pd.DataFrame(dict(pdiv_id=w.pdiv_id.values, year=yr,
                                     cdl_code=code, cdl_mode_code_250m=mode, mode_frac_250m=np.round(frac, 3))))
        print(f"{yr}: sampled {ok.sum()} points", flush=True)
    df = pd.concat(out, ignore_index=True)
    for col, cls_col, name_col in [("cdl_code", "cdl_class", "cdl_name"),
                                   ("cdl_mode_code_250m", "cdl_mode_class_250m", None)]:
        v = df[col].values
        df[cls_col] = np.where(v >= 0, np.array(CROP_CLASSES)[lut[np.clip(v, 0, 255)]], None)
        if name_col:
            df[name_col] = [NAMES.get(int(k), f"CDL code {k}") if k >= 0 else None for k in v]
        df[col] = df[col].where(df[col] >= 0).astype("Int64")
    df.to_parquet(PROC / "cdl_points.parquet", index=False)
    print(df[df.year == df.year.max()].cdl_mode_class_250m.value_counts().to_string())


if __name__ == "__main__":
    main()
