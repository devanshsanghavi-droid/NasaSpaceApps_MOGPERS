"""hazard module: NASA POWER daily drought hazard per county x year, 1981-2025.

Inputs
  data/processed/counties.parquet (geo module: fips, lon, lat interior point). If it is missing, interior points
  are computed here from the Census cb_2023_us_county_500k file (geometry.representative_point()).
Outputs
  data/raw/power/<cell_id>_1981_2025.json.gz       raw POWER daily point JSON per MERRA-2 cell (cache)
  data/processed/power_cells.parquet                cell_id, lon, lat, elev_m, n_counties, fips (list)
  data/processed/power_daily_cells.parquet          cell_id, date, daily vars (float32), if < ~150 MB
  data/processed/hazard_county_year.parquet         (fips, year) 1981-2025 drought hazard metrics

POWER meteorology is MERRA-2 on its native 0.5 deg lat x 0.625 deg lon grid (cell centres: lat multiple of 0.5,
lon multiple of 0.625; verified in shared/central_iowa_pipeline notes/conf.md). Counties are deduplicated to the cell
containing their interior point and the API is queried at the cell centre.

Re-run: /home/user/venv-db/bin/python pipeline/hazard_power.py   (skips cached cells)
"""
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "power"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)

STATES = {"17": "IL", "19": "IA", "20": "KS", "27": "MN", "29": "MO", "31": "NE", "46": "SD"}
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "GWETROOT", "GWETTOP", "QV2M", "RH2M"]
START, END = 1981, 2025
BASE0, BASE1 = 1991, 2020
DLAT, DLON = 0.5, 0.625
URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
UA = {"User-Agent": "drought-bill-hackathon"}
MAX_WORKERS = 5


# ---------------------------------------------------------------- counties and cells
def load_counties():
    f = PROC / "counties.parquet"
    if f.exists():
        c = pd.read_parquet(f)[["fips", "state_abbr", "name", "lon", "lat"]]
        c.attrs["source"] = "data/processed/counties.parquet (geo module)"
        return c
    import geopandas as gpd  # fallback only
    z = ROOT / "data" / "raw" / "census" / "cb_2023_us_county_500k.zip"
    if not z.exists():
        z.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get("https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip",
                         headers=UA, timeout=300)
        r.raise_for_status()
        z.write_bytes(r.content)
    g = gpd.read_file(f"zip://{z}")
    g = g[g.STATEFP.isin(STATES)].copy()
    pts = g.to_crs(5070).geometry.representative_point().to_crs(4326)
    c = pd.DataFrame({"fips": g.GEOID.values, "state_abbr": g.STATEFP.map(STATES).values, "name": g.NAME.values,
                      "lon": pts.x.values, "lat": pts.y.values})
    c.to_parquet(RAW / "county_points_fallback.parquet", index=False)
    c.attrs["source"] = "Census cb_2023_us_county_500k representative_point (fallback)"
    return c


def cell_of(lon, lat):
    return round(round(lat / DLAT) * DLAT, 4), round(round(lon / DLON) * DLON, 4)


def cell_id(lat, lon):
    return f"p{lat:.2f}_{lon:.3f}"


def build_cells(counties):
    la_lo = [cell_of(lo, la) for lo, la in zip(counties.lon, counties.lat)]
    counties = counties.assign(cell_lat=[a for a, _ in la_lo], cell_lon=[b for _, b in la_lo])
    counties["cell_id"] = [cell_id(a, b) for a, b in zip(counties.cell_lat, counties.cell_lon)]
    cells = (counties.groupby(["cell_id", "cell_lat", "cell_lon"])["fips"].apply(lambda s: sorted(s)).reset_index()
             .rename(columns={"cell_lat": "lat", "cell_lon": "lon"}))
    cells["n_counties"] = cells.fips.str.len()
    return counties, cells


# ---------------------------------------------------------------- POWER fetch
def cache_path(cid):
    return RAW / f"{cid}_{START}_{END}.json.gz"


def fetch(cid, lat, lon):
    f = cache_path(cid)
    if f.exists() and f.stat().st_size > 1000:
        return cid, "cached"
    params = dict(parameters=",".join(PARAMS), community="AG", longitude=lon, latitude=lat,
                  start=f"{START}0101", end=f"{END}1231", format="JSON")
    last = None
    for attempt in range(8):
        try:
            r = requests.get(URL, params=params, headers=UA, timeout=300)
            if r.status_code == 200:
                d = r.json()
                p = d["properties"]["parameter"]
                assert all(k in p for k in PARAMS), f"missing params {set(PARAMS) - set(p)}"
                tmp = f.with_suffix(".tmp")
                with gzip.open(tmp, "wt") as fh:
                    json.dump(d, fh)
                tmp.rename(f)
                return cid, "fetched"
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 403, 404, 422):
                break
        except Exception as e:  # noqa: BLE001
            last = repr(e)
        time.sleep(min(120, 5 * 2 ** attempt))
    return cid, f"FAILED {last}"


def fetch_all(cells):
    jobs = [(r.cell_id, r.lat, r.lon) for r in cells.itertuples()]
    status = {}
    t0 = time.time()
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futs = [ex.submit(fetch, *j) for j in jobs]
        for i, fu in enumerate(as_completed(futs), 1):
            cid, s = fu.result()
            status[cid] = s
            if i % 25 == 0 or s.startswith("FAILED"):
                print(f"  {i}/{len(jobs)} {cid} {s} ({time.time() - t0:.0f}s)", flush=True)
    return status


def read_cell(cid):
    with gzip.open(cache_path(cid), "rt") as fh:
        d = json.load(fh)
    p = d["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(p[k], dtype="float64") for k in PARAMS})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.mask(df <= -998.0)  # fill_value -999
    df = df.astype("float32").rename_axis("date").reset_index()
    df.insert(0, "cell_id", cid)
    return df, float(d["geometry"]["coordinates"][2]), d["header"]


# ---------------------------------------------------------------- derived daily quantities
def sine_dd_above(tmin, tmax, thr):
    """Single-sine degree-days above thr (Baskerville & Emin 1969), degC-day per day."""
    tmin = np.asarray(tmin, float)
    tmax = np.asarray(tmax, float)
    out = np.zeros_like(tmin)
    m = (tmax + tmin) / 2.0
    a = (tmax - tmin) / 2.0
    full = tmin >= thr
    out[full] = m[full] - thr
    part = (tmax > thr) & (tmin < thr)
    with np.errstate(invalid="ignore", divide="ignore"):
        th = np.arcsin(np.clip((thr - m[part]) / a[part], -1, 1))
        out[part] = ((m[part] - thr) * (np.pi / 2 - th) + a[part] * np.cos(th)) / np.pi
    out[np.isnan(tmin) | np.isnan(tmax)] = np.nan
    return out


def es_kpa(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def add_daily(d, elev):
    """d: one cell's daily frame. VPD per FAO-56: es = mean(es(Tmax), es(Tmin)); ea from QV2M and pressure from
    elevation (FAO-56 eq. 7). Fallback to RH2M-based ea where QV2M is missing."""
    tmn, tmx = d.T2M_MIN.to_numpy(float), d.T2M_MAX.to_numpy(float)
    d["edd30"] = sine_dd_above(tmn, tmx, 30.0)
    d["gdd10_30"] = sine_dd_above(tmn, tmx, 10.0) - d["edd30"]
    p_kpa = 101.3 * ((293.0 - 0.0065 * elev) / 293.0) ** 5.26
    q = d.QV2M.to_numpy(float) / 1000.0
    ea = q * p_kpa / (0.622 + 0.378 * q)
    ea_rh = es_kpa(d.T2M.to_numpy(float)) * d.RH2M.to_numpy(float) / 100.0
    ea = np.where(np.isnan(ea), ea_rh, ea)
    es = (es_kpa(tmx) + es_kpa(tmn)) / 2.0
    d["vpd"] = np.clip(es - ea, 0, None)
    return d


def cell_year(d):
    d = d.copy()
    d["year"] = d.date.dt.year
    m = d.date.dt.month
    jja, ja, mjjas = m.between(6, 8), m.isin([7, 8]), m.between(5, 9)

    def agg(mask, col, fn, min_count):
        g = d.loc[mask].groupby("year")[col]
        return g.sum(min_count=min_count) if fn == "sum" else g.mean().where(g.count() >= min_count)

    out = pd.DataFrame({
        "prcp_jja_mm": agg(jja, "PRECTOTCORR", "sum", 92),
        "prcp_jul_mm": agg(m == 7, "PRECTOTCORR", "sum", 31),
        "prcp_aug_mm": agg(m == 8, "PRECTOTCORR", "sum", 31),
        "prcp_mjjas_mm": agg(mjjas, "PRECTOTCORR", "sum", 153),
        "edd30_jja": agg(jja, "edd30", "sum", 92),
        "gdd10_30_mjjas": agg(mjjas, "gdd10_30", "sum", 153),
        "tmax_jja_c": agg(jja, "T2M_MAX", "mean", 92),
        "vpd_jja_kpa": agg(jja, "vpd", "mean", 92),
        "gwetroot_jja": agg(jja, "GWETROOT", "mean", 92),
        "gwetroot_jul_aug": agg(ja, "GWETROOT", "mean", 62),
        "gwettop_jja": agg(jja, "GWETTOP", "mean", 92),
        "n_days": d.groupby("year").size(),
    })
    out.index.name = "year"
    return out.reset_index()


# ---------------------------------------------------------------- standardisation (per cell, base 1991-2020)
def spi_gamma(x, base):
    """SPI: gamma (2-parameter, loc=0, MLE) fit to the 1991-2020 values, mixed with P(0) for zero totals."""
    b = base[~np.isnan(base)]
    if len(b) < 20:
        return np.full_like(x, np.nan)
    pos = b[b > 0]
    q0 = 1 - len(pos) / len(b)
    a, _, scale = stats.gamma.fit(pos, floc=0)
    cdf = q0 + (1 - q0) * stats.gamma.cdf(np.where(x > 0, x, 0), a, loc=0, scale=scale)
    cdf = np.where(x <= 0, q0 if q0 > 0 else 1e-6, cdf)
    return stats.norm.ppf(np.clip(cdf, 1e-6, 1 - 1e-6))


def emp_pct(x, base):
    b = np.sort(base[~np.isnan(base)])
    lo = np.searchsorted(b, x, side="left")
    hi = np.searchsorted(b, x, side="right")
    return np.where(np.isnan(x), np.nan, 100.0 * (lo + 0.5 * (hi - lo)) / len(b))


def zscore(x, base):
    b = base[~np.isnan(base)]
    sd = b.std(ddof=1)
    if not np.isfinite(sd) or sd < 1e-9:
        return np.full_like(x, np.nan)
    return (x - b.mean()) / sd


def standardise(cy):
    parts = []
    for cid, g in cy.groupby("cell_id"):
        g = g.sort_values("year").copy()
        inb = g.year.between(BASE0, BASE1).to_numpy()
        pj = g.prcp_jja_mm.to_numpy(float)
        g["prcp_jja_anom_pct"] = 100.0 * (pj / np.nanmean(pj[inb]) - 1.0)
        g["spi_jja"] = spi_gamma(pj, pj[inb])
        gw = g.gwetroot_jja.to_numpy(float)
        g["gwetroot_jja_pct"] = emp_pct(gw, gw[inb])
        ed = g.edd30_jja.to_numpy(float)
        sp = g.spi_jja.to_numpy(float)
        g["z_neg_spi_jja"] = zscore(-sp, -sp[inb])
        g["z_edd30_jja"] = zscore(ed, ed[inb])
        g["z_neg_gwetroot_jja"] = zscore(-gw, -gw[inb])
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)
    zc = ["z_neg_spi_jja", "z_edd30_jja", "z_neg_gwetroot_jja"]
    out["hazard_n_components"] = out[zc].notna().sum(axis=1)
    out["hazard_z"] = out[zc].mean(axis=1, skipna=True).where(out.hazard_n_components > 0)
    return out


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    counties = load_counties()
    print("counties:", len(counties), "from", counties.attrs.get("source"))
    counties, cells = build_cells(counties)
    print("unique POWER cells:", len(cells))
    status = fetch_all(cells)
    failed = {k: v for k, v in status.items() if v.startswith("FAILED")}
    print(f"fetch done in {time.time() - t0:.0f}s; fetched={sum(v == 'fetched' for v in status.values())} "
          f"cached={sum(v == 'cached' for v in status.values())} failed={len(failed)}")
    if failed:
        (RAW / "fetch_failures.json").write_text(json.dumps(failed, indent=1))

    daily_frames, cy_frames, elev, header = [], [], {}, None
    for cid in cells.cell_id:
        if not cache_path(cid).exists():
            continue
        d, el, header = read_cell(cid)
        elev[cid] = el
        daily_frames.append(d)
        cy = cell_year(add_daily(d.copy(), el))
        cy.insert(0, "cell_id", cid)
        cy_frames.append(cy)
    print("POWER header:", json.dumps(header))
    cells["elev_m"] = cells.cell_id.map(elev)
    cells["fetch_status"] = cells.cell_id.map(lambda c: "ok" if c in elev else status.get(c, "missing"))
    cells[["cell_id", "lon", "lat", "elev_m", "n_counties", "fips", "fetch_status"]].to_parquet(
        PROC / "power_cells.parquet", index=False)

    daily = pd.concat(daily_frames, ignore_index=True)
    print("daily rows:", len(daily), "missing share:", daily[PARAMS].isna().mean().round(5).to_dict())
    dpath = PROC / "power_daily_cells.parquet"
    daily.to_parquet(dpath, index=False, compression="zstd")
    size_mb = dpath.stat().st_size / 1e6
    print(f"power_daily_cells.parquet {size_mb:.1f} MB")
    if size_mb > 150:
        alt = RAW / "power_daily_cells.parquet"
        dpath.rename(alt)
        print("  > 150 MB, moved to", alt)

    cy = standardise(pd.concat(cy_frames, ignore_index=True))
    hz = counties[["fips", "state_abbr", "name", "cell_id", "cell_lon", "cell_lat"]].rename(
        columns={"cell_id": "power_cell_id", "cell_lon": "power_cell_lon", "cell_lat": "power_cell_lat"})
    years = pd.DataFrame({"year": range(START, END + 1)})
    hz = hz.merge(years, how="cross").merge(cy.rename(columns={"cell_id": "power_cell_id"}),
                                             on=["power_cell_id", "year"], how="left")
    last_day = daily.date.max()
    hz["is_partial_year"] = (hz.year == last_day.year) & (last_day < pd.Timestamp(f"{last_day.year}-12-31"))
    cols = ["fips", "year", "state_abbr", "name", "power_cell_id", "power_cell_lon", "power_cell_lat",
            "prcp_jja_mm", "prcp_jul_mm", "prcp_aug_mm", "prcp_mjjas_mm", "prcp_jja_anom_pct", "spi_jja",
            "edd30_jja", "gdd10_30_mjjas", "tmax_jja_c", "vpd_jja_kpa", "gwetroot_jja", "gwetroot_jul_aug",
            "gwetroot_jja_pct", "gwettop_jja", "z_neg_spi_jja", "z_edd30_jja", "z_neg_gwetroot_jja",
            "hazard_n_components", "hazard_z", "n_days", "is_partial_year"]
    hz = hz[cols].sort_values(["fips", "year"]).reset_index(drop=True)
    fl = hz.select_dtypes("float64").columns
    hz[fl] = hz[fl].round(4)
    hz.to_parquet(PROC / "hazard_county_year.parquet", index=False)
    print("hazard_county_year rows:", len(hz), "counties:", hz.fips.nunique(),
          "years:", hz.year.min(), hz.year.max())
    print(hz[cols[7:]].describe().T[["count", "mean", "min", "max"]].round(3).to_string())
    print(f"total runtime {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
