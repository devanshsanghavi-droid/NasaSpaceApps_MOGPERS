"""NASA POWER daily weather at each region county centroid (1984-2025) + FAO-56 Penman-Monteith reference ET0.

Source: NASA POWER Daily API v2 (community=AG), one request per county centroid:
  https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN,RH2M,T2MDEW,WS2M,
      ALLSKY_SFC_SW_DWN,PRECTOTCORR,PS&community=AG&longitude=<lon>&latitude=<lat>&start=19840101&end=20251231&format=JSON
  (MERRA-2 meteorology, CERES/SRB solar, PRECTOTCORR = bias-corrected MERRA-2 precipitation; native 0.5 x 0.625 deg,
   solar 1 x 1 deg). Centroids: equal-area centroid of each Census 2023 county polygon (nasa_common.region_counties).
Raw JSON cached in data/raw/power/<fips>.json; daily table with ET0 cached in data/raw/power/power_county_daily.parquet.

ET0 (mm/day), FAO-56 (Allen et al. 1998) daily grass-reference Penman-Monteith, eq. 6:
  ET0 = [0.408 D (Rn - G) + g 900/(T+273) u2 (es - ea)] / [D + g (1 + 0.34 u2)]
  T = (Tmax+Tmin)/2; D = slope of the saturation vapour pressure curve at T (eq. 13);
  g = 0.000665 P with P = POWER surface pressure PS (kPa) (eq. 8);
  es = [e0(Tmax)+e0(Tmin)]/2 (eq. 12); ea = e0(Tdew) using POWER T2MDEW (eq. 14);
  Rs = ALLSKY_SFC_SW_DWN (MJ m-2 d-1); Ra from latitude and day of year (eq. 21); Rso = (0.75 + 2e-5 z) Ra (eq. 37),
  z = POWER cell elevation (m, returned by the API); Rns = 0.77 Rs (albedo 0.23); Rnl from eq. 39 with Rs/Rso capped at 1;
  Rn = Rns - Rnl; G = 0 for daily steps; u2 = WS2M (already at 2 m).
Annual products (complete calendar years): precip_in, precip_gs_in (Apr-Sep), et0_in, et0_gs_in, tmax_jja_f (mean of
daily Tmax over Jun-Aug, F), tmean_f (annual mean of (Tmax+Tmin)/2, F), n_days.
Output: data/processed/power_county_annual.parquet (+ data/processed/power_region_daily.parquet: region-mean daily
precip/ET0/Tmax, used e.g. to find mid-summer dry spells for HLS).
Re-run: python3 pipeline/nasa_power.py
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nasa_common import PROC, RAW, http_get, region_counties  # noqa: E402

D = RAW / "power"
D.mkdir(parents=True, exist_ok=True)
API = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M_MAX", "T2M_MIN", "RH2M", "T2MDEW", "WS2M", "ALLSKY_SFC_SW_DWN", "PRECTOTCORR", "PS"]
START, END = "19840101", "20251231"
MM_PER_IN = 25.4


def fetch(row):
    f = D / f"{row.fips}.json"
    if f.exists():
        return row.fips, json.loads(f.read_text())
    params = dict(parameters=",".join(PARAMS), community="AG", longitude=row.lon, latitude=row.lat,
                  start=START, end=END, format="JSON")
    r = http_get(API, params=params, timeout=300)
    j = r.json()
    f.write_text(json.dumps(j))
    time.sleep(0.5)
    return row.fips, j


def e0(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def fao56_et0(tmax, tmin, tdew, u2, rs, p_kpa, lat_deg, doy, z_m):
    t = (tmax + tmin) / 2
    delta = 4098 * e0(t) / (t + 237.3) ** 2
    gamma = 0.000665 * p_kpa
    es = (e0(tmax) + e0(tmin)) / 2
    ea = e0(tdew)
    phi = np.deg2rad(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))
    rso = (0.75 + 2e-5 * z_m) * ra
    rns = 0.77 * rs
    sigma = 4.903e-9
    ratio = np.clip(rs / rso, 0.25, 1.0)
    rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * \
        (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return np.maximum(et0, 0)


def to_frame(fips, j):
    p = j["properties"]["parameter"]
    df = pd.DataFrame({k: pd.Series(v) for k, v in p.items()})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(-999.0, np.nan)
    lon, lat, z = j["geometry"]["coordinates"]
    df["et0_mm"] = fao56_et0(df.T2M_MAX.values, df.T2M_MIN.values, df.T2MDEW.values, df.WS2M.values,
                             df.ALLSKY_SFC_SW_DWN.values, df.PS.values, lat, df.index.dayofyear.values, z)
    df["fips"] = fips
    df["power_lon"], df["power_lat"], df["power_elev_m"] = lon, lat, z
    return df.rename_axis("date").reset_index()


def annual(daily):
    d = daily.copy()
    d["year"] = d.date.dt.year
    d["gs"] = d.date.dt.month.between(4, 9)
    d["jja"] = d.date.dt.month.between(6, 8)
    out = []
    for (f, y), g in d.groupby(["fips", "year"]):
        gs, jja = g[g.gs], g[g.jja]
        out.append(dict(
            county_fips=f, year=y,
            precip_in=g.PRECTOTCORR.sum(min_count=360) / MM_PER_IN,
            precip_gs_in=gs.PRECTOTCORR.sum(min_count=180) / MM_PER_IN,
            et0_in=g.et0_mm.sum(min_count=360) / MM_PER_IN,
            et0_gs_in=gs.et0_mm.sum(min_count=180) / MM_PER_IN,
            tmax_jja_f=jja.T2M_MAX.mean() * 9 / 5 + 32,
            tmean_f=((g.T2M_MAX + g.T2M_MIN) / 2).mean() * 9 / 5 + 32,
            n_days=int(g.et0_mm.notna().sum())))
    return pd.DataFrame(out)


def main():
    counties = region_counties()
    with ThreadPoolExecutor(3) as ex:
        res = dict(ex.map(fetch, counties.itertuples()))
    daily = pd.concat([to_frame(f, j) for f, j in res.items()], ignore_index=True)
    daily = daily.merge(counties[["fips", "lon", "lat"]].rename(columns={"lon": "centroid_lon", "lat": "centroid_lat"}),
                        on="fips")
    daily.to_parquet(D / "power_county_daily.parquet", index=False)
    ann = annual(daily)
    for c in ["precip_in", "precip_gs_in", "et0_in", "et0_gs_in", "tmax_jja_f", "tmean_f"]:
        ann[c] = ann[c].round(3)
    ann["source"] = "NASA POWER daily v2 AG (MERRA-2/CERES); ET0 FAO-56 PM"
    ann.to_parquet(PROC / "power_county_annual.parquet", index=False)
    reg = daily.groupby("date")[["PRECTOTCORR", "et0_mm", "T2M_MAX", "T2M_MIN"]].mean().round(3).reset_index()
    reg.columns = ["date", "precip_mm", "et0_mm", "tmax_c", "tmin_c"]
    reg.to_parquet(PROC / "power_region_daily.parquet", index=False)
    print(ann.groupby("year")[["precip_in", "precip_gs_in", "et0_in", "et0_gs_in", "tmax_jja_f"]].mean().round(2).to_string())
    print("counties", ann.county_fips.nunique(), "years", ann.year.min(), ann.year.max(), "rows", len(ann))
    print("distinct POWER cells", daily[["power_lon", "power_lat"]].drop_duplicates().shape[0])


if __name__ == "__main__":
    main()
