"""storms module, optional step: SMAP L4 root-zone soil moisture per basin (needs NASA Earthdata credentials).

Runs ONLY if EARTHDATA_TOKEN is set or ~/.netrc has a `machine urs.earthdata.nasa.gov` entry; otherwise prints
why and exits 0, so the pipeline never depends on it. On 2026-11-14 there were no credentials and the data host
(data.nsidc.earthdatacloud.nasa.gov) was blocked by the container proxy (see BLOCKERS.md, "storms / Earthdata").

What it would do: search CMR for SPL4SMGP (SMAP L4 Global 3-hourly 9 km EASE-Grid 2.0 surface and root-zone soil
moisture, https://nsidc.org/data/spl4smgp) over the basins, download ONE granule per day (the 12:00-15:00 UTC
window, ~7 am CDT; ~140 MB each), read Geophysical_Data/sm_rootzone and sm_surface (m3/m3), average the 9 km cells
whose centres fall inside each basin, and write data/processed/smap_l4_basin_daily.parquet
(basin, date, sm_rootzone, sm_surface, n_cells). The model could then use sm_rootzone in place of (or beside)
POWER GWETROOT for 2015-04..present.

Env: SMAP_START (default 30 days ago), SMAP_END (default 3 days ago). Raw granules: data/raw/smap/ (deleted after
reading unless KEEP_RAW=1). Re-run: python3 pipeline/p16_smap_optional.py
"""
import datetime as dt
import netrc
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import PROC, RAW  # noqa: E402

BBOX = (-96.2, 41.4, -93.5, 44.3)


def credentials():
    if os.environ.get("EARTHDATA_TOKEN"):
        return "environment"  # earthaccess reads EARTHDATA_TOKEN (or EARTHDATA_USERNAME/PASSWORD)
    try:
        if netrc.netrc().authenticators("urs.earthdata.nasa.gov"):
            return "netrc"
    except (FileNotFoundError, netrc.NetrcParseError):
        pass
    return None


def main():
    strat = credentials()
    if not strat:
        print("p16_smap_optional: no EARTHDATA_TOKEN and no urs.earthdata.nasa.gov entry in ~/.netrc -> skipping "
              "SMAP L4 (optional; the model uses POWER GWETROOT instead). See BLOCKERS.md 'storms / Earthdata'.")
        return 0
    try:
        import earthaccess
        import h5py
    except ImportError as e:
        print(f"p16_smap_optional: credentials found but {e.name} is not installed: pip install -q earthaccess h5py")
        return 0
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    today = dt.date.today()
    start = os.environ.get("SMAP_START", (today - dt.timedelta(days=30)).isoformat())
    end = os.environ.get("SMAP_END", (today - dt.timedelta(days=3)).isoformat())
    auth = earthaccess.login(strategy=strat)
    if not auth or not getattr(auth, "authenticated", False):
        print(f"p16_smap_optional: Earthdata login via {strat} failed -> skipping.")
        return 0
    res = earthaccess.search_data(short_name="SPL4SMGP", bounding_box=BBOX, temporal=(start, end))
    # one granule per day: the file whose name has T133000 (centre of the 12-15 UTC window)
    res = [g for g in res if "T133000" in str(g.data_links()[0])]
    print(f"SPL4SMGP granules {start}..{end}: {len(res)} (one per day)")
    if not res:
        return 0
    raw = RAW / "smap"
    raw.mkdir(parents=True, exist_ok=True)
    try:
        files = earthaccess.download(res, str(raw))
    except Exception as e:  # noqa: BLE001  (e.g. proxy 403 on data.nsidc.earthdatacloud.nasa.gov)
        print(f"p16_smap_optional: download failed: {type(e).__name__}: {e} -> skipping.")
        return 0

    d = pd.read_parquet(PROC / "huc12.parquet")
    basins = gpd.GeoDataFrame(d, geometry=gpd.GeoSeries.from_wkb(d.geometry), crs=4326).dissolve("basin")
    masks = None
    rows = []
    for f in sorted(files):
        with h5py.File(f, "r") as h:
            if masks is None:
                lat, lon = h["cell_lat"][:], h["cell_lon"][:]
                sel = (lon >= BBOX[0]) & (lon <= BBOX[2]) & (lat >= BBOX[1]) & (lat <= BBOX[3])
                ii, jj = np.where(sel)
                pts = gpd.GeoSeries(gpd.points_from_xy(lon[ii, jj], lat[ii, jj]), crs=4326)
                masks = {b: (ii[pts.within(g).values], jj[pts.within(g).values]) for b, g in basins.geometry.items()}
            rz = h["Geophysical_Data/sm_rootzone"][:]
            sf = h["Geophysical_Data/sm_surface"][:]
        date = pd.to_datetime(os.path.basename(f).split("_")[4][:8]).date()
        for b, (i, j) in masks.items():
            vr, vs = rz[i, j], sf[i, j]
            vr, vs = vr[vr >= 0], vs[vs >= 0]  # fill = -9999
            rows.append(dict(basin=b, date=date, sm_rootzone=float(vr.mean()) if vr.size else None,
                             sm_surface=float(vs.mean()) if vs.size else None, n_cells=int(len(i))))
        if not os.environ.get("KEEP_RAW"):
            os.remove(f)
    out = pd.DataFrame(rows)
    fo = PROC / "smap_l4_basin_daily.parquet"
    if fo.exists():
        out = pd.concat([pd.read_parquet(fo), out]).drop_duplicates(["basin", "date"], keep="last")
    out.sort_values(["basin", "date"]).to_parquet(fo, index=False, compression="zstd")
    print(f"wrote {fo}: {len(out)} rows")
    print(out.groupby("basin")[["sm_rootzone", "sm_surface"]].describe().round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
