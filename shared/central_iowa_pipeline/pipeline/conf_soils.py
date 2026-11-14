"""conf module: gNATSGO soils for all 50,850 grid points.

 1. gnatsgo-rasters (Planetary Computer, 10 m, ESRI:102039 Albers): for each of the 2 STAC items covering the
    tile, read a window enclosing the grid points at the 20 m overview (nearest) per asset and sample the pixel
    containing each point. Cached as data/raw/gnatsgo/<item>_<asset>.npz.
 2. USDA Soil Data Access (SDA): for each unique mukey, dominant component (max comppct_r) and its surface
    horizon (min hzdept_r): kwfact, om_r, claytotal_r, sandtotal_r; component drainagecl, hydgrp.
Output: data/raw/conf/soils_points.parquet (merged by conf_assemble.py)
Re-run: .venv/bin/python pipeline/conf_soils.py
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.windows import Window

os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "gnatsgo"
SDA_RAW = ROOT / "data" / "raw" / "sda"
OUT = ROOT / "data" / "raw" / "conf"
for p in (RAW, SDA_RAW, OUT):
    p.mkdir(parents=True, exist_ok=True)
REGION = json.loads((ROOT / "data" / "region.json").read_text())
ASSETS = ["mukey", "aws0_100", "soc0_30", "nccpi3corn", "nccpi3soy", "droughty", "rootznaws"]
DEC = 2  # 20 m overview


def grid_points():
    g = REGION["grid"]
    rows, cols = np.meshgrid(np.arange(g["nrows"]), np.arange(g["ncols"]), indexing="ij")
    rows = rows.ravel(); cols = cols.ravel()
    return pd.DataFrame(dict(grid_id=rows * g["ncols"] + cols,
                             x=g["x0"] + cols * g["spacing_m"], y=g["y0"] - rows * g["spacing_m"]))


def items():
    c = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                  modifier=planetary_computer.sign_inplace)
    return list(c.search(collections=["gnatsgo-rasters"], bbox=REGION["tile_bounds_lonlat"]).items())


def read_asset(item, asset, xa, ya):
    f = RAW / f"{item.id}_{asset}.npz"
    if f.exists():
        v = np.load(f)["vals"]
        if asset in ("aws0_100", "soc0_30", "rootznaws"):
            v = np.where(v < 0, np.nan, v)
        return v
    href = planetary_computer.sign(item.assets[asset].href)
    with rasterio.open(href) as src:
        tr = src.transform
        colf = (xa - tr.c) / tr.a
        rowf = (ya - tr.f) / tr.e
        inside = (colf >= 0) & (rowf >= 0) & (colf < src.width) & (rowf < src.height)
        vals = np.full(xa.shape, np.nan)
        if inside.any():
            c0 = max(int(np.floor(colf[inside].min())) - 4, 0)
            r0 = max(int(np.floor(rowf[inside].min())) - 4, 0)
            c1 = min(int(np.ceil(colf[inside].max())) + 4, src.width)
            r1 = min(int(np.ceil(rowf[inside].max())) + 4, src.height)
            c0 -= c0 % DEC; r0 -= r0 % DEC
            wdt = (c1 - c0) // DEC * DEC; hgt = (r1 - r0) // DEC * DEC
            arr = src.read(1, window=Window(c0, r0, wdt, hgt), out_shape=(hgt // DEC, wdt // DEC),
                           resampling=Resampling.nearest).astype(np.float64)
            nod = src.nodata
            if nod is not None:
                arr[arr == nod] = np.nan
            arr[arr <= -9999] = np.nan
            if asset in ("aws0_100", "soc0_30", "rootznaws"):
                arr[arr < 0] = np.nan  # physically impossible; a handful of sentinel-like negatives
            if asset == "mukey":
                arr[arr >= 2147483647] = np.nan
            if asset == "aws0_100":
                arr[arr >= 2147483648] = np.nan
            ci = ((colf[inside] - c0) // DEC).astype(int).clip(0, arr.shape[1] - 1)
            ri = ((rowf[inside] - r0) // DEC).astype(int).clip(0, arr.shape[0] - 1)
            vals[inside] = arr[ri, ci]
    np.savez_compressed(f, vals=vals)
    print("read", item.id, asset, "valid", np.isfinite(vals).sum(), flush=True)
    return vals


SQL = """
SELECT mu.mukey, mu.muname, c.cokey, c.compname, c.comppct_r, c.slope_r, c.drainagecl, c.hydgrp,
       h.hzname, h.hzdept_r, h.hzdepb_r, h.kwfact, h.om_r, h.claytotal_r, h.sandtotal_r
FROM mapunit mu
INNER JOIN component c ON c.mukey = mu.mukey AND c.cokey =
    (SELECT TOP 1 c2.cokey FROM component c2 WHERE c2.mukey = mu.mukey ORDER BY c2.comppct_r DESC, c2.cokey)
LEFT JOIN chorizon h ON h.cokey = c.cokey AND h.chkey =
    (SELECT TOP 1 h2.chkey FROM chorizon h2 WHERE h2.cokey = c.cokey ORDER BY h2.hzdept_r ASC, h2.chkey)
WHERE mu.mukey IN ({keys})
"""


def sda_batch(i, keys):
    f = SDA_RAW / f"v2_batch_{i:03d}_{len(keys)}_{keys[0]}.json"
    if f.exists():
        return json.loads(f.read_text())
    q = SQL.format(keys=",".join(str(k) for k in keys))
    last = None
    for attempt in range(5):
        try:
            r = requests.post("https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
                              data={"query": q, "format": "JSON+COLUMNNAME"},
                              headers={"User-Agent": "counterfield-hackathon"}, timeout=180)
            if r.status_code == 200:
                d = r.json()
                f.write_text(json.dumps(d))
                return d
            last = f"HTTP {r.status_code} {r.text[:300]}"
        except Exception as e:  # noqa
            last = repr(e)
    raise RuntimeError(last)


def sda(mukeys):
    mukeys = sorted(int(m) for m in mukeys)
    batches = [mukeys[i:i + 400] for i in range(0, len(mukeys), 400)]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda a: sda_batch(*a), enumerate(batches)))
    rows = []
    for d in res:
        tab = d.get("Table", [])
        if not tab:
            continue
        cols = tab[0]
        rows += [dict(zip(cols, r)) for r in tab[1:]]
    df = pd.DataFrame(rows)
    for c in ["mukey", "comppct_r", "slope_r", "hzdept_r", "hzdepb_r", "kwfact", "om_r", "claytotal_r", "sandtotal_r"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mukey"] = df.mukey.astype("int64")
    return df.drop_duplicates("mukey")


def main():
    pts = grid_points()
    to_alb = Transformer.from_crs("EPSG:32615", "ESRI:102039", always_xy=True)
    xa, ya = to_alb.transform(pts.x.values, pts.y.values)
    its = items()
    print("items", [i.id for i in its])
    jobs = [(it, a) for it in its for a in ASSETS]
    with ThreadPoolExecutor(7) as ex:
        res = list(ex.map(lambda j: read_asset(j[0], j[1], xa, ya), jobs))
    vals = {}
    for (it, a), v in zip(jobs, res):
        if a not in vals:
            vals[a] = v.copy()
        else:
            m = np.isnan(vals[a]) & np.isfinite(v)
            vals[a][m] = v[m]
    out = pts[["grid_id"]].copy()
    for a in ASSETS:
        out[a] = vals[a]
    out["mukey"] = out.mukey.astype("Int64")
    tab = sda(out.mukey.dropna().unique())
    tab.to_parquet(SDA_RAW / "sda_dominant_component_surface.parquet", index=False)
    print("SDA rows", len(tab), "of", out.mukey.nunique(), "mukeys")
    tab = tab.rename(columns={"claytotal_r": "clay_pct", "sandtotal_r": "sand_pct"})
    keep = ["mukey", "muname", "compname", "comppct_r", "slope_r", "hzname", "hzdept_r", "hzdepb_r",
            "kwfact", "om_r", "clay_pct", "sand_pct", "drainagecl", "hydgrp"]
    out = out.merge(tab[keep].astype({"mukey": "Int64"}), on="mukey", how="left")
    out["field_id"] = ["f%05d" % g for g in out.grid_id]
    out.to_parquet(OUT / "soils_points.parquet", index=False)
    print(out.describe(include="all").T.round(3).to_string())


if __name__ == "__main__":
    main()
