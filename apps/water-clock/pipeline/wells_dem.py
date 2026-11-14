"""Sample NASADEM (NASA SRTM reprocessed, 1 arc-second) ground elevation at every well location.

Used by wells_process.py as a sanity check on the land-surface altitude reported for each well (a wrong land altitude
gives a wrong water-level elevation and saturated thickness). Source: Microsoft Planetary Computer STAC collection
"nasadem" (COGs on nasademeuwest.blob.core.windows.net), read window-by-window with rasterio, no full-tile download.

Input:  data/raw/kgs/<fips>_sites.csv and data/raw/nwis/<fips>_ml_*.json (via wells_process loaders)
Output: data/raw/nasadem/wells_nasadem.parquet  (well_id, lon, lat, nasadem_m, nasadem_ft)  - cache, gitignored
Run:    python3 pipeline/wells_dem.py   (before wells_process.py)
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wells_process import load_kgs, load_nwis, RAW, BBOX  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
OUT = RAW / "nasadem"
OUT.mkdir(parents=True, exist_ok=True)
GDAL_ENV = dict(GDAL_HTTP_USERAGENT="water-clock-hackathon", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="2")
if os.path.exists("/root/.ccr/ca-bundle.crt"):
    GDAL_ENV["CURL_CA_BUNDLE"] = "/root/.ccr/ca-bundle.crt"


def main():
    import pystac_client
    import planetary_computer
    km, _ = load_kgs()
    nm, _ = load_nwis()
    w = pd.concat([km[["well_id", "lon", "lat"]], nm[["well_id", "lon", "lat"]]]).drop_duplicates("well_id")
    w = w.dropna(subset=["lon", "lat"]).reset_index(drop=True)
    cat = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=["nasadem"], bbox=[BBOX[0] - 0.1, BBOX[1] - 0.1, BBOX[2] + 0.1, BBOX[3] + 0.1]).items())
    w["nasadem_m"] = np.nan
    for it in items:
        lon0, lat0, lon1, lat1 = it.bbox
        sel = w.lon.between(lon0, lon1) & w.lat.between(lat0, lat1) & w.nasadem_m.isna()
        if not sel.any():
            continue
        with rasterio.Env(**GDAL_ENV), rasterio.open(it.assets["elevation"].href) as src:
            vals = np.array([v[0] for v in src.sample(list(zip(w.lon[sel], w.lat[sel])))], dtype=float)
            if src.nodata is not None:
                vals[vals == src.nodata] = np.nan
        w.loc[sel, "nasadem_m"] = vals
        print(it.id, int(sel.sum()), flush=True)
    w["nasadem_ft"] = w.nasadem_m / 0.3048
    w["source_url"] = "https://planetarycomputer.microsoft.com/dataset/nasadem"
    w.to_parquet(OUT / "wells_nasadem.parquet", index=False)
    print("wells sampled", int(w.nasadem_m.notna().sum()), "of", len(w))


if __name__ == "__main__":
    main()
