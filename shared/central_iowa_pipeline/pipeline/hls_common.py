"""Shared helpers for the COUNTERFIELD 'hls' module (grid, signing, retrying reads, indices, checkpoints)."""
import json, os, time, random, datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import planetary_computer
import rasterio

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "hls"
SCENES = RAW / "scenes"
REGION = json.loads((ROOT / "data" / "region.json").read_text())
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MULTIPLEX="YES",
    GDAL_HTTP_TIMEOUT="60",
    GDAL_HTTP_USERAGENT="counterfield-hackathon",
    VSI_CACHE="FALSE",
)


def grid():
    """All 50,850 grid points: grid_id, row, col, x, y (UTM 15N), field_id."""
    g = REGION["grid"]
    rows, cols = np.meshgrid(np.arange(g["nrows"]), np.arange(g["ncols"]), indexing="ij")
    rows = rows.ravel(); cols = cols.ravel()
    gid = rows * g["ncols"] + cols
    x = g["x0"] + cols * g["spacing_m"]
    y = g["y0"] - rows * g["spacing_m"]
    fid = np.array([f"f{i:05d}" for i in gid])
    return pd.DataFrame({"grid_id": gid.astype(np.int32), "row": rows, "col": cols,
                         "x": x.astype(float), "y": y.astype(float), "field_id": fid})


def unsigned(href):
    return href.split("?")[0]


def read_overview(href, ov_level=0, retries=7):
    """Read band 1 of a COG at overview level `ov_level` (0 = first overview, 2x decimation; overviews are
    NEAREST-resampled in HLS v2, so values are actual 30 m pixels). Re-signs the URL on every attempt so an expired SAS
    token is refreshed. Returns (array, transform, nodata)."""
    last = None
    for a in range(retries):
        try:
            url = planetary_computer.sign(unsigned(href))
            with rasterio.Env(**GDAL_ENV):
                kw = {} if ov_level is None else {"OVERVIEW_LEVEL": ov_level}
                with rasterio.open(url, **kw) as ds:
                    arr = ds.read(1)
                    return arr, ds.transform, ds.nodata
        except Exception as e:  # transient HTTP / 403 token expiry
            last = e
            time.sleep(min(60, 2 ** a + random.random() * 2))
    raise RuntimeError(f"read failed after {retries} tries: {unsigned(href)} :: {last}")


def pixel_index(transform, x, y, shape):
    """Vectorised row/col of the pixel containing each (x, y); returns (r, c, inside_mask)."""
    inv = ~transform
    c, r = inv * (x, y)
    r = np.floor(r).astype(np.int64); c = np.floor(c).astype(np.int64)
    inside = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
    return np.clip(r, 0, shape[0] - 1), np.clip(c, 0, shape[1] - 1), inside


def indices(blue, green, red, nir, swir1, swir2):
    """Inputs: float reflectance (0-1). Returns dict of float32 indices."""
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
        ndti = (swir1 - swir2) / (swir1 + swir2)
        gcvi = nir / green - 1.0
        bsi = ((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))
    return {k: v.astype(np.float32) for k, v in dict(ndvi=ndvi, ndti=ndti, gcvi=gcvi, bsi=bsi).items()}


SCHEMA = pa.schema([
    ("field_id", pa.string()), ("grid_id", pa.int32()), ("date", pa.date32()),
    ("sensor", pa.string()), ("product", pa.string()), ("doy", pa.int16()),
    ("ndvi", pa.float32()), ("ndti", pa.float32()), ("gcvi", pa.float32()), ("bsi", pa.float32()),
    ("blue", pa.int16()), ("green", pa.int16()), ("red", pa.int16()), ("nir", pa.int16()),
    ("swir1", pa.int16()), ("swir2", pa.int16()),
    ("water", pa.bool_()), ("aerosol", pa.int8()), ("fmask_clear", pa.bool_()),
])


def write_scene(item_id, df, meta):
    """Checkpoint one scene: rows parquet + manifest json (json written last = scene done)."""
    SCENES.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    tmp = SCENES / f"{item_id}.parquet.tmp"
    pq.write_table(tbl, tmp, compression="zstd")
    os.replace(tmp, SCENES / f"{item_id}.parquet")
    tmpj = SCENES / f"{item_id}.json.tmp"
    tmpj.write_text(json.dumps(meta))
    os.replace(tmpj, SCENES / f"{item_id}.json")


def scene_done(item_id):
    return (SCENES / f"{item_id}.json").exists() and (SCENES / f"{item_id}.parquet").exists()


def build_rows(g, sel, date, sensor, product, refl, water, aerosol):
    """refl: dict band->int16 sample arrays (scaled x1e4, for selected points only)."""
    f = {k: v.astype(np.float32) * 1e-4 for k, v in refl.items()}
    ix = indices(f["blue"], f["green"], f["red"], f["nir"], f["swir1"], f["swir2"])
    n = int(sel.sum())
    df = pd.DataFrame({
        "field_id": g["field_id"].values[sel], "grid_id": g["grid_id"].values[sel],
        "date": np.repeat(pd.Timestamp(date).date(), n),
        "sensor": sensor, "product": product,
        "doy": np.int16(pd.Timestamp(date).dayofyear),
        **ix,
        **{k: v.astype(np.int16) for k, v in refl.items()},
        "water": water.astype(bool), "aerosol": aerosol.astype(np.int8), "fmask_clear": True,
    })
    return df
