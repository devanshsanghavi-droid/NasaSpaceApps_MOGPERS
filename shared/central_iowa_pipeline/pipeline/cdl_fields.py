"""Build data/fields.parquet (owner: cdl module).

Inputs (cached, produced by cdl_fetch_pc.py and cdl_download_nass.py):
  data/raw/cdl/cdl_<year>_tile.tif   (USDA CDL 30 m, EPSG:5070, tile window) for 2008-2024
  data/raw/cdl/census/cb_2023_us_county_500k.zip  (Census cartographic boundary counties)

For every grid point (region.json grid, UTM 15N) take the CDL class of the 30 m pixel containing
the point and the share of the 3x3 block equal to that class, for each year.

Usage: .venv/bin/python pipeline/cdl_fields.py
"""
import os, sys, re
import requests
from collections import Counter
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import ROOT, region  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw", "cdl")
OUT = os.path.join(ROOT, "data", "fields.parquet")
YEARS = list(range(2008, 2025))
PANEL = list(range(2016, 2025))
COUNTY_ZIP = os.path.join(RAW, "census", "cb_2023_us_county_500k.zip")
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip"

# CDL code -> sequence letter
LETTER = {}
for c in (1, 12, 13, 241):  # corn, sweet corn, pop/orn corn, dbl corn/soy
    LETTER[c] = "C"
LETTER[5] = "S"; LETTER[240] = "S"; LETTER[239] = "S"  # soybeans, dbl soybeans/oats, dbl soybeans/cotton
for c in (2, 3, 4, 6, 10, 11, 41, 42, 43):   # other row crops: cotton, rice, sorghum, sunflower, peanuts, tobacco, sugarbeets, dry beans, potatoes
    LETTER[c] = "R"
for c in (22, 23, 24, 26, 225, 236, 238):     # durum, spring, winter wheat, dbl winwht/soy, winwht/corn, winwht/sorghum, winwht/cotton
    LETTER[c] = "W"
for c in (21, 25, 27, 28, 30, 205, 237, 254):  # barley, other small grains, rye, oats, speltz, triticale, dbl barley/corn, dbl barley/soy
    LETTER[c] = "O"
for c in (36, 37, 58):                        # alfalfa, other hay/non-alfalfa, clover/wildflowers
    LETTER[c] = "H"
for c in (59, 60, 62, 176):                   # sod/grass seed, switchgrass, pasture/grass (pre-2011 code), grassland/pasture
    LETTER[c] = "P"
# Contract: "corn/soy/other-row-crop". Small grains (O) and wheat (W) are NOT row crops, so they do not qualify.
FIELD_LETTERS = set("CSR")  # corn, soy, other row crops (incl. double crops led by those)


def letter(code):
    if code is None or (isinstance(code, float) and np.isnan(code)):
        return "?"
    return LETTER.get(int(code), "X")


def ensure_county_zip():
    if os.path.exists(COUNTY_ZIP):
        return
    os.makedirs(os.path.dirname(COUNTY_ZIP), exist_ok=True)
    print("downloading", COUNTY_URL, flush=True)
    for k in range(4):
        try:
            r = requests.get(COUNTY_URL, headers={"User-Agent": "counterfield-hackathon"}, timeout=120)
            r.raise_for_status()
            tmp = COUNTY_ZIP + ".tmp"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, COUNTY_ZIP)
            return
        except Exception as e:
            print(f"  county zip retry {k}: {e}", flush=True)
    raise RuntimeError(f"could not download {COUNTY_URL}")


def grid_points():
    r = region(); g = r["grid"]
    rows, cols = np.meshgrid(np.arange(g["nrows"]), np.arange(g["ncols"]), indexing="ij")
    rows = rows.ravel(); cols = cols.ravel()
    x = g["x0"] + cols * g["spacing_m"]
    y = g["y0"] - rows * g["spacing_m"]
    gid = rows * g["ncols"] + cols
    df = pd.DataFrame({"field_id": [f"f{i:05d}" for i in gid], "grid_id": gid.astype(np.int32),
                       "row": rows.astype(np.int16), "col": cols.astype(np.int16), "x": x, "y": y})
    lon, lat = Transformer.from_crs(32615, 4326, always_xy=True).transform(x, y)
    df["lon"] = lon; df["lat"] = lat
    return df


def sample_year(path, X, Y):
    with rasterio.open(path) as src:
        assert src.crs.to_epsg() == 5070
        arr = src.read(1)
        inv = ~src.transform
        c, r = inv * (X, Y)
        c = np.floor(c).astype(int); r = np.floor(r).astype(int)
        assert c.min() >= 1 and r.min() >= 1 and c.max() < arr.shape[1] - 1 and r.max() < arr.shape[0] - 1
        center = arr[r, c]
        same = np.zeros(len(X), np.int16)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                same += (arr[r + dr, c + dc] == center)
        return center.astype(np.int16), same, src.tags().get("source", "")


def classify(seq):
    """Rotation pattern label for a 9-letter 2016-2024 sequence (only meaningful for fields)."""
    if seq in ("CSCSCSCSC", "SCSCSCSCS"):
        return "corn-soy strict alternation"
    if set(seq) <= {"C", "S"}:
        nc = seq.count("C")
        if nc >= 7:
            return "continuous / mostly corn (>=7 C)"
        if seq.count("S") >= 7:
            return "mostly soybean (>=7 S)"
        return "corn-soy with breaks (repeat years)"
    if set(seq) & {"R"}:
        return "includes other row crop"
    if set(seq) & {"O", "W"}:
        return "includes small grains / wheat"
    if set(seq) & {"H", "P"}:
        return "includes hay / pasture"
    return "other"


def regime_by_year(seq):
    """Per-pair regime: 'R' rotation (crop differs from previous year), 'M' monoculture (same crop)."""
    return "".join("M" if a == b else "R" for a, b in zip(seq[:-1], seq[1:]))


def main():
    df = grid_points()
    X, Y = Transformer.from_crs(32615, 5070, always_xy=True).transform(df.x.values, df.y.values)
    sources = {}
    for yr in YEARS:
        p = os.path.join(RAW, f"cdl_{yr}_tile.tif")
        if not os.path.exists(p):
            print(f"WARNING: {yr} missing -> null"); df[f"cdl_{yr}"] = pd.array([pd.NA] * len(df), dtype="Int16")
            df[f"homog_{yr}"] = np.nan; sources[yr] = None
            continue
        center, same, src = sample_year(p, X, Y)
        df[f"cdl_{yr}"] = pd.array(center, dtype="Int16")
        df[f"homog_{yr}"] = (same / 9.0).astype(np.float32)
        sources[yr] = "NASS national zip" if src.startswith("http") else src.split(":")[0]
    # counties
    ensure_county_zip()
    cty = gpd.read_file(f"zip://{COUNTY_ZIP}")
    pts = gpd.GeoDataFrame(df[["field_id"]], geometry=gpd.points_from_xy(df.lon, df.lat), crs="EPSG:4326").to_crs(cty.crs)
    j = gpd.sjoin(pts, cty[["GEOID", "NAME", "STUSPS", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()]
    df["county_fips"] = j["GEOID"].astype("string").values
    df["county_name"] = j["NAME"].astype("string").values
    # field rule on the 2016-2024 panel
    L = np.array([[letter(v) for v in df[f"cdl_{yr}"].astype("float").values] for yr in PANEL]).T  # (n, 9)
    df["crop_seq_2016_2024"] = ["".join(r) for r in L]
    H = np.stack([df[f"homog_{yr}"].values for yr in PANEL], 1)
    # a year counts only if BOTH the crop qualifies AND the 3x3 block is homogeneous (>=7 of 9 pixels == centre)
    ok = np.isin(L, list(FIELD_LETTERS)) & (np.nan_to_num(H) >= 7 / 9 - 1e-6)
    df["is_field"] = ok.sum(1) >= 7

    cols = (["field_id", "grid_id", "row", "col", "x", "y", "lon", "lat", "county_fips", "county_name"]
            + [f"cdl_{y}" for y in YEARS] + [f"homog_{y}" for y in YEARS] + ["is_field", "crop_seq_2016_2024"])
    df = df[cols]
    df.to_parquet(OUT, index=False)
    print(f"wrote {OUT}: {len(df)} rows, {df.is_field.sum()} is_field")
    print("sources:", sources)
    report(df)


def report(df):
    f = df[df.is_field]
    print("\n== is_field:", int(df.is_field.sum()), "of", len(df), f"({df.is_field.mean():.1%})")
    print("\n== is_field by county")
    print(df.groupby(["county_fips", "county_name"]).is_field.agg(["sum", "count"]).sort_values("sum", ascending=False).to_string())
    print("\n== rotation pattern (fields)")
    print(f.crop_seq_2016_2024.map(classify).value_counts().to_string())
    print("\n== top 15 sequences (fields)")
    print(f.crop_seq_2016_2024.value_counts().head(15).to_string())
    reg = f.crop_seq_2016_2024.map(regime_by_year)
    has_R3 = reg.str.contains("RRR"); has_M2 = reg.str.contains("MM")
    first = reg.str[:4]; last = reg.str[4:]
    print("\n== pattern switching (fields)")
    print("  strict alternation all 9 years:", int(f.crop_seq_2016_2024.isin(["CSCSCSCSC", "SCSCSCSCS"]).sum()))
    print("  >=1 repeat year (same crop twice in a row):", int(reg.str.contains("M").sum()))
    print("  both a >=4-yr alternating run and a >=3-yr monoculture run (regime switch):", int((has_R3 & has_M2).sum()))
    print("  rotation 2016-2020 (no repeats) -> repeat(s) 2020-2024:", int(((first == "RRRR") & last.str.contains("M")).sum()))
    print("  repeat(s) 2016-2020 -> rotation 2020-2024 (no repeats):", int((first.str.contains("M") & (last == "RRRR")).sum()))
    cc = f.crop_seq_2016_2024.str.count("C")
    print("  corn years per field (2016-2024):", cc.value_counts().sort_index().to_dict())
    print("\n== CDL class frequency at all points, 2024 / 2016 / 2008")
    for y in (2024, 2016, 2008):
        print(y, df[f"cdl_{y}"].value_counts().head(10).to_dict())
    print("\n== mean homog (all points / fields):", {y: (round(float(df[f'homog_{y}'].mean()), 3), round(float(f[f'homog_{y}'].mean()), 3)) for y in (2008, 2016, 2021, 2022, 2024)})


if __name__ == "__main__":
    main()
