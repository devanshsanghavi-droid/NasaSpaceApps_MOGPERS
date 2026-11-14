"""Build data/processed/grace_maps.json (small map grids + region trend summary) from the GRACE caches.

Inputs (produced by nasa_grace_da.py and nasa_grace_gfz.py):
  data/raw/grace_da/maps_cache.npz  GRACE-DA gws_inst percentile, annual means of the monthly samples (0.125 deg,
                                    HP_BBOX) + the latest weekly field
  data/raw/gfz/trend_grids.npz      per-cell TWS trend (GFZ GravIS, 1 deg) and G3P groundwater trend (0.5 deg), cm/yr
  data/raw/gfz/gfz_summary.json     region-mean trends
Grids are lists of rows from NORTH to SOUTH (row 0 = northernmost), columns WEST to EAST; values rounded; NaN -> null.
`lat`/`lon` give cell-centre coordinates; `bbox` gives the outer cell edges [W, S, E, N].
Re-run: python3 pipeline/nasa_grace_maps.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import BBOX, PROC, RAW  # noqa: E402

MAP_YEARS = ["2003", "2004", "2012", "2024"]


def grid_out(a, nd=0):
    a = np.asarray(a, float)
    return [[None if not np.isfinite(v) else (int(round(v)) if nd == 0 else round(float(v), nd)) for v in row] for row in a]


def clip(lat, lon, a, box, pad=0.0):
    i = (lat >= box[1] - pad) & (lat <= box[3] + pad)
    j = (lon >= box[0] - pad) & (lon <= box[2] + pad)
    la, lo, sub = lat[i], lon[j], a[..., i, :][..., j]
    order = np.argsort(-la)  # north -> south
    return la[order], lo, sub[..., order, :]


def coarsen2(lat, lon, a):
    ny, nx = (len(lat) // 2) * 2, (len(lon) // 2) * 2
    a = a[..., :ny, :nx]
    sh = a.shape[:-2] + (ny // 2, 2, nx // 2, 2)
    with np.errstate(all="ignore"):
        import warnings
        warnings.simplefilter("ignore")
        c = np.nanmean(a.reshape(sh), axis=(-3, -1))
    return lat[:ny].reshape(-1, 2).mean(1), lon[:nx].reshape(-1, 2).mean(1), c


def block(lat, lon, grids, dlat, dlon, nd=0):
    return dict(cell_deg=dlat, lat=[round(float(x), 4) for x in lat], lon=[round(float(x), 4) for x in lon],
                bbox=[round(float(lon.min() - dlon / 2), 4), round(float(lat.min() - dlat / 2), 4),
                      round(float(lon.max() + dlon / 2), 4), round(float(lat.max() + dlat / 2), 4)],
                **{k: grid_out(v, nd) for k, v in grids.items()})


def main():
    z = np.load(RAW / "grace_da" / "maps_cache.npz")
    lat, lon, years, ann = z["lat"].astype(float), z["lon"].astype(float), list(z["years"]), z["ann"]
    latest, latest_date = z["latest"], str(z["latest_date"])
    sel = [years.index(y) for y in MAP_YEARS if y in years]
    cube = np.concatenate([ann[sel], latest[None]], axis=0)
    labels = [years[k] for k in sel] + [f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"]
    kinds = ["annual mean of monthly samples"] * len(sel) + ["single weekly field (latest)"]
    la, lo, sub = clip(lat, lon, cube, BBOX, pad=0.07)
    region = block(la, lo, {}, 0.125, 0.125)
    region.update(dates=labels, date_kind=kinds, gws_pct=[grid_out(g) for g in sub])
    order = np.argsort(-lat)
    cla, clo, csub = coarsen2(lat[order], lon, cube[:, order, :])
    context = block(cla, clo, {}, 0.25, 0.25)
    context.update(dates=labels, date_kind=kinds, gws_pct=[grid_out(g) for g in csub])
    all_years = {y: round(float(np.nanmean(ann[k][z["region_mask"]])), 1) for k, y in enumerate(years)}
    out = dict(
        description="GRACE maps for the Water Clock region. gws_pct = GRACE-DA groundwater storage PERCENTILE (0-100, "
                    "relative to 1948-2012 climatology; <=10 = exceptional-to-extreme drought class, NDMC). "
                    "tws_trend_cm_yr = GFZ GravIS RL06 TWS linear trend (cm/yr equivalent water height, with annual + "
                    "semi-annual terms) per 1 deg cell; g3p_gws_trend_cm_yr = G3P v1.12 groundwater-storage trend per "
                    "0.5 deg cell. Rows north->south, columns west->east, null = no data.",
        sources={"grace_da": "https://nasagrace.unl.edu/data/YYYYMMDD/GRACEDADM_CLSM0125US_7D.AYYYYMMDD.030.nc4",
                 "gfz_tws": "https://isdc-data.gfz.de/grace/GravIS/GFZ/Level-3/TWS/GRAVIS-3_GFZOP_0600_TWS_GRID_GFZ_0006.nc",
                 "g3p": "https://isdc-data.gfz.de/grace/GravIS/G3P/v1.12/G3P_v1.12.zip"},
        cell_deg=0.125, bbox=region["bbox"], dates=labels, gws_pct=region["gws_pct"],
        region=region, context_high_plains=context,
        region_annual_gws_pct=all_years,
    )
    tg = RAW / "gfz" / "trend_grids.npz"
    if tg.exists():
        t = np.load(tg)
        la1, lo1 = t["lat_1deg"].astype(float), t["lon_1deg"].astype(float)
        o = np.argsort(-la1)
        out["tws_trend_cm_yr"] = block(la1[o], lo1, {"2003_latest": t["tws_trend_2003_latest"][o],
                                                      "2003_2016": t["tws_trend_2003_2016"][o]}, 1.0, 1.0, nd=2)
        if "g3p_gws_trend_2003_latest" in t:
            lg, og = t["lat_g3p"].astype(float), t["lon_g3p"].astype(float)
            o = np.argsort(-lg)
            out["g3p_gws_trend_cm_yr"] = block(lg[o], og, {"2003_2023": t["g3p_gws_trend_2003_latest"][o]}, 0.5, 0.5, nd=2)
    gs = RAW / "gfz" / "gfz_summary.json"
    if gs.exists():
        s = json.loads(gs.read_text())
        out["region_trends_cm_yr"] = s["trends"]
        out["region_trend_method"] = ("Area-weighted region mean (cells weighted by area inside the 26 GMD1/3/4 counties); "
                                      "OLS with annual+semi-annual harmonics on monthly values, gap months omitted; "
                                      "SE inflated for lag-1 residual autocorrelation.")
        out["gfz_sources"] = s["sources"]
    p = PROC / "grace_maps.json"
    p.write_text(json.dumps(out, separators=(",", ":")))
    print(p, p.stat().st_size, "bytes")
    print("region grid", len(region["lat"]), "x", len(region["lon"]), "context", len(context["lat"]), "x", len(context["lon"]))
    print("labels", labels)
    print("region annual gws_pct", all_years)


if __name__ == "__main__":
    main()
