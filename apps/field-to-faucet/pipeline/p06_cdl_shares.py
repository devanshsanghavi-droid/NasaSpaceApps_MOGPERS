"""Land-cover shares per HUC-12 and per basin from the CDL clips (p05), 2016-2025.

Outputs
- data/processed/cdl_huc12_year.parquet  key (huc12, year)
- data/processed/cdl_basin_year.parquet  key (basin, year)
- data/raw/cdl/rowcrop_years_2016_2025.tif  uint8 count of years (0-10) each 30 m pixel is a row crop (letters C/S/R);
  "row-crop pixel" elsewhere in this module = row crop in >= 6 of the 10 years (majority).
- data/raw/cdl/huc12_index_30m.tif  int16 index into the sorted huc12 list (-1 = outside both basins).

Shares are of the HUC-12 / basin area (pixels whose centre falls inside the polygon, CDL code > 0).
Class groups follow the crop letters of shared notes/cdl.md (C,S,W,R,O,H,P,X); X is split further into
forest / developed / water_wetland / other.
"""
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import rasterize

from common import RAW, PROC

CDL = RAW / "cdl"
YEARS = list(range(2016, 2026))

LETTER_CODES = {
    "C": [1, 12, 13, 241],
    "S": [5, 239, 240],
    "W": [22, 23, 24, 26, 225, 236, 238],
    "R": [2, 3, 4, 6, 10, 11, 41, 42, 43],
    "O": [21, 25, 27, 28, 30, 205, 237, 254],
    "H": [36, 37, 58],
    "P": [59, 60, 62, 176],
}
FOREST = [63, 141, 142, 143]
DEVELOPED = [82, 121, 122, 123, 124]
WATER_WETLAND = [83, 87, 92, 111, 190, 195]
# cultivated cropland (all NASS crop classes, incl. fallow 61 and tree/specialty crops); excludes grass/pasture
CROPLAND = [c for c in list(range(1, 59)) + [61] + list(range(66, 81)) + list(range(204, 255))]


def lut(codes):
    t = np.zeros(256, bool)
    t[codes] = True
    return t


GROUPS = {
    "corn": lut(LETTER_CODES["C"]),
    "soy": lut(LETTER_CODES["S"]),
    "other_row": lut(LETTER_CODES["R"]),
    "small_grain": lut(LETTER_CODES["W"] + LETTER_CODES["O"]),
    "hay": lut(LETTER_CODES["H"]),
    "grass_pasture": lut(LETTER_CODES["P"]),
    "forest": lut(FOREST),
    "developed": lut(DEVELOPED),
    "water_wetland": lut(WATER_WETLAND),
}
ROWCROP = GROUPS["corn"] | GROUPS["soy"] | GROUPS["other_row"]
CROPLAND_LUT = lut(CROPLAND)


def letter_lut():
    """uint8 code -> crop letter (for other modules)."""
    t = np.array(["X"] * 256, dtype="<U1")
    for k, v in LETTER_CODES.items():
        t[v] = k
    return t


def huc_index(prof):
    df = pd.read_parquet(PROC / "huc12.parquet").sort_values("huc12").reset_index(drop=True)
    g = gpd.GeoSeries.from_wkb(df.geometry, crs=4326).to_crs(5070)
    f = CDL / "huc12_index_30m.tif"
    if f.exists():
        with rasterio.open(f) as s:
            idx = s.read(1)
    else:
        idx = rasterize(((geom, i) for i, geom in enumerate(g)), out_shape=(prof["height"], prof["width"]),
                        transform=prof["transform"], fill=-1, dtype="int16")
        p = dict(prof, dtype="int16", nodata=-1)
        with rasterio.open(f, "w", **p) as d:
            d.write(idx, 1)
    return df, idx


def main():
    paths = {y: CDL / f"cdl_{y}_basins.tif" for y in YEARS}
    missing = [y for y, p in paths.items() if not (p.exists() and (CDL / f"DONE_{y}").exists())]
    assert not missing, f"CDL clips missing for {missing}; run p05_cdl_fetch.py"
    with rasterio.open(paths[YEARS[0]]) as s:
        prof = s.profile
        tr0 = s.transform
    df, idx = huc_index(prof)
    nh = len(df)
    inside = idx >= 0
    hi = idx[inside].astype(np.int64)
    rc_count = np.zeros(idx.shape, np.uint8)
    rows = []
    for y in YEARS:
        with rasterio.open(paths[y]) as s:
            assert s.transform == tr0 and s.shape == idx.shape, (y, s.transform)
            a = s.read(1)
        rc_count += ROWCROP[a]
        v = a[inside].astype(np.int64)
        cnt = np.bincount(hi * 256 + v, minlength=nh * 256).reshape(nh, 256)
        valid = cnt[:, 1:].sum(1)
        rec = pd.DataFrame({"huc12": df.huc12, "basin": df.basin, "year": y,
                            "npix": valid, "nodata_frac": cnt[:, 0] / np.maximum(cnt.sum(1), 1)})
        for name, t in GROUPS.items():
            rec[name + "_px"] = cnt[:, t].sum(1)
        rec["cropland_px"] = cnt[:, CROPLAND_LUT].sum(1)
        rows.append(rec)
        print(f"{y}: corn {cnt[:, GROUPS['corn']].sum() / valid.sum():.3f} soy "
              f"{cnt[:, GROUPS['soy']].sum() / valid.sum():.3f} (both basins)", flush=True)
        del a
    p = dict(prof, dtype="uint8", nodata=255)
    with rasterio.open(CDL / "rowcrop_years_2016_2025.tif", "w", **p) as d:
        d.write(rc_count, 1)
        d.update_tags(description="number of years 2016-2025 the pixel is CDL row crop (corn/soy/other row: "
                                  "letters C,S,R); row-crop pixel = count >= 6")
    px = pd.concat(rows, ignore_index=True)

    def shares(g, keys):
        out = g[keys].copy() if keys else pd.DataFrame(index=g.index)
        n = g["npix"].astype(float)
        for name in GROUPS:
            out[name] = g[name + "_px"] / n
        out["row_crop"] = (g["corn_px"] + g["soy_px"] + g["other_row_px"]) / n
        out["other"] = 1 - out[list(GROUPS)].sum(axis=1)
        out["cropland_km2"] = g["cropland_px"] * 900 / 1e6
        out["area_km2"] = n * 900 / 1e6
        return out

    cols = ["huc12", "year", "corn", "soy", "row_crop", "small_grain", "hay", "grass_pasture", "forest",
            "developed", "water_wetland", "other_row", "other", "cropland_km2", "area_km2"]
    h = shares(px, ["huc12", "basin", "year"])
    h = h[cols[:2] + ["basin"] + cols[2:]]
    for c in cols[2:-2]:
        h[c] = h[c].astype("float32").round(4)
    h["cropland_km2"] = h.cropland_km2.round(3)
    h["area_km2"] = h.area_km2.round(3)
    h.to_parquet(PROC / "cdl_huc12_year.parquet", index=False, compression="zstd")

    b = px.groupby(["basin", "year"], as_index=False).sum(numeric_only=True)
    bs = shares(b, ["basin", "year"])
    bs = bs[["basin"] + cols[1:]]
    for c in cols[2:-2]:
        bs[c] = bs[c].astype("float32").round(4)
    bs.to_parquet(PROC / "cdl_basin_year.parquet", index=False, compression="zstd")

    pd.set_option("display.width", 200)
    print(f"cdl_huc12_year: {len(h)} rows ({h.huc12.nunique()} HUC-12 x {h.year.nunique()} yrs); "
          f"max nodata_frac {px.nodata_frac.max():.4f}")
    print(f"cdl_basin_year: {len(bs)} rows")
    print(bs[["basin", "year", "corn", "soy", "row_crop", "small_grain", "hay", "grass_pasture", "forest",
              "developed", "water_wetland", "cropland_km2", "area_km2"]].round(3).to_string(index=False))
    rc = rc_count[inside]
    print(f"row-crop pixels (>=6 of 10 yrs) share of basin area: {np.mean(rc >= 6):.3f}; "
          f"pixels row crop all 10 yrs: {np.mean(rc == 10):.3f}")


if __name__ == "__main__":
    main()
