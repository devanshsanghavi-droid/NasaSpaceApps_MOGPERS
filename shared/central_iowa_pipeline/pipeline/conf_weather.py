"""conf module: NASA POWER daily weather for the MERRA-2 cells covering tile 15TVG.

Outputs
  data/weather_daily_power.parquet  (power_cell_id, date) raw POWER daily 1981-2024
  data/raw/power/weather_annual_power.parquet  annual POWER-derived metrics (IMERG fields are
      merged in by conf_assemble.py which writes data/weather_annual.parquet)

POWER meteorology is MERRA-2 on its native 0.5 deg lat x 0.625 deg lon grid (verified by probing
the API: values change at lat x.25/x.75 and lon -94.0625/-93.4375/...). Cell centres are lat
multiples of 0.5 and lon multiples of 0.625. Solar (ALLSKY_SFC_SW_DWN) is on a 1 deg grid.
Re-run: .venv/bin/python pipeline/conf_weather.py
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "power"
RAW.mkdir(parents=True, exist_ok=True)
REGION = json.loads((ROOT / "data" / "region.json").read_text())

PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "RH2M", "GWETROOT", "GWETTOP", "ALLSKY_SFC_SW_DWN"]
START, END = 1981, 2024
DLAT, DLON = 0.5, 0.625
UA = {"User-Agent": "counterfield-hackathon"}


def cell_centers():
    lon0, lat0, lon1, lat1 = REGION["tile_bounds_lonlat"]
    lats = np.arange(math.floor((lat0 + DLAT / 2) / DLAT) * DLAT, lat1 + DLAT / 2 + 1e-9, DLAT)
    lats = [la for la in lats if la + DLAT / 2 > lat0 and la - DLAT / 2 < lat1]
    lons = np.arange(math.floor((lon0 + DLON / 2) / DLON) * DLON, lon1 + DLON / 2 + 1e-9, DLON)
    lons = [lo for lo in lons if lo + DLON / 2 > lon0 and lo - DLON / 2 < lon1]
    return [(round(float(la), 4), round(float(lo), 4)) for la in lats for lo in lons]


def cell_id(lat, lon):
    return f"p{lat:.2f}_{lon:.3f}"


def fetch(lat, lon, y0, y1):
    f = RAW / f"{cell_id(lat, lon)}_{y0}_{y1}.json"
    if f.exists() and f.stat().st_size > 1000:
        return json.loads(f.read_text())
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = dict(parameters=",".join(PARAMS), community="AG", longitude=lon, latitude=lat,
                  start=f"{y0}0101", end=f"{y1}1231", format="JSON")
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=300)
            if r.status_code == 200:
                d = r.json()
                f.write_text(json.dumps(d))
                return d
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:  # noqa
            last = repr(e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"POWER fetch failed {lat},{lon},{y0}-{y1}: {last}")


def daily_frame():
    cells = cell_centers()
    chunks = [(y, min(y + 10, END)) for y in range(START, END + 1, 11)]
    jobs = [(la, lo, a, b) for la, lo in cells for a, b in chunks]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda j: (j, fetch(*j)), jobs))
    frames = []
    for (la, lo, a, b), d in res:
        p = d["properties"]["parameter"]
        df = pd.DataFrame({k: pd.Series(p[k]) for k in PARAMS})
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.replace(-999.0, np.nan)
        df["power_cell_id"] = cell_id(la, lo)
        df["cell_lat"] = la
        df["cell_lon"] = lo
        df["cell_elev_m"] = d["geometry"]["coordinates"][2]
        frames.append(df)
    out = pd.concat(frames).rename_axis("date").reset_index()
    out = out.sort_values(["power_cell_id", "date"]).drop_duplicates(["power_cell_id", "date"])
    cols = ["power_cell_id", "date", "cell_lat", "cell_lon", "cell_elev_m"] + PARAMS
    return out[cols].reset_index(drop=True)


def sine_dd_above(tmin, tmax, thr):
    """Single-sine degree-days above threshold (Baskerville & Emin 1969), deg C-day per day."""
    tmin = np.asarray(tmin, float); tmax = np.asarray(tmax, float)
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


def tetens_es(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def annual(daily):
    d = daily.copy()
    d["year"] = d.date.dt.year
    d["month"] = d.date.dt.month
    d["doy"] = d.date.dt.dayofyear
    tmx = d.T2M_MAX.clip(upper=30.0)
    tmn = d.T2M_MIN.clip(lower=10.0)
    tmx = np.maximum(tmx, 10.0)
    tmn = np.minimum(tmn, 30.0)
    d["gdd"] = (tmx + tmn) / 2.0 - 10.0
    d["dd30"] = sine_dd_above(d.T2M_MIN, d.T2M_MAX, 30.0)
    d["vpd"] = tetens_es(d.T2M) * (1 - d.RH2M / 100.0)
    rows = []
    for (cid, yr), g in d.groupby(["power_cell_id", "year"]):
        m = g.month
        frost_spring = g[(g.T2M_MIN <= 0.0) & (m < 7)]
        frost_fall = g[(g.T2M_MIN <= 0.0) & (m >= 7)]
        n_year = len(g)
        rows.append(dict(
            power_cell_id=cid, year=int(yr),
            gdd_may_sep=g.loc[m.between(5, 9), "gdd"].sum(min_count=150),
            hdd30_jul_aug=g.loc[m.isin([7, 8]), "dd30"].sum(min_count=60),
            days_tmax30_jul_aug=int((g.loc[m.isin([7, 8]), "T2M_MAX"] > 30.0).sum()),
            prcp_amj=g.loc[m.between(4, 6), "PRECTOTCORR"].sum(min_count=90),
            prcp_jja=g.loc[m.between(6, 8), "PRECTOTCORR"].sum(min_count=90),
            prcp_annual=g["PRECTOTCORR"].sum(min_count=360),
            tmax_jul=g.loc[m == 7, "T2M_MAX"].mean(),
            vpd_jja=g.loc[m.between(6, 8), "vpd"].mean(),
            gwetroot_apr=g.loc[m == 4, "GWETROOT"].mean(),
            gwettop_amj=g.loc[m.between(4, 6), "GWETTOP"].mean(),
            srad_jja=g.loc[m.between(6, 8), "ALLSKY_SFC_SW_DWN"].mean(),
            frost_last_spring_doy=int(frost_spring.doy.max()) if len(frost_spring) else np.nan,
            frost_first_fall_doy=int(frost_fall.doy.min()) if len(frost_fall) else np.nan,
            n_days=n_year,
        ))
    return pd.DataFrame(rows)


def main():
    print("cells:", cell_centers())
    daily = daily_frame()
    daily.to_parquet(ROOT / "data" / "weather_daily_power.parquet", index=False)
    print("daily rows", len(daily), daily.date.min(), daily.date.max())
    print(daily.isna().mean().round(4).to_dict())
    ann = annual(daily)
    ann.to_parquet(RAW / "weather_annual_power.parquet", index=False)
    print("annual rows", len(ann))
    print(ann.describe().T[["mean", "min", "max"]].round(2))


if __name__ == "__main__":
    main()
