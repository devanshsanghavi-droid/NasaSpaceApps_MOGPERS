"""USGS NWIS daily nitrate (99133) and discharge (00060) at the two Des Moines intake gauges.

Daily values (dv, statCd 00003) 2015-10-01..yesterday, plus a fill from instantaneous values (iv, 15-min)
for recent days (last IV_DAYS days) that are missing in dv: daily mean of the local-day readings, kept only
when >= IV_MIN_READINGS of 96 readings exist; flagged src='iv'.
Output: data/processed/nwis_daily.parquet (full calendar grid per site; NaN where no data).
Raw JSON cached in data/raw/nwis/ (dv cached per water year; the current water year and iv are re-fetched).
"""
import datetime as dt
import json
import sys

import numpy as np
import pandas as pd

from common import RAW, PROC, SITES, CFS_MGL_TO_KG_DAY, MCL, get

DV = "https://waterservices.usgs.gov/nwis/dv/"
IV = "https://waterservices.usgs.gov/nwis/iv/"
START = dt.date(2015, 10, 1)
TODAY = dt.date.today()
LAST_FULL = TODAY - dt.timedelta(days=1)  # today's dv value is a partial-day mean: excluded
IV_DAYS = 120
IV_MIN_READINGS = 80
PARAMS = {"99133": "no3", "00060": "q"}
CACHE = RAW / "nwis"
CACHE.mkdir(parents=True, exist_ok=True)
NODATA = -999999.0


def fetch(url, params, fname, refresh):
    f = CACHE / fname
    if f.exists() and not refresh:
        return json.loads(f.read_text())
    js = get(url, params=params, timeout=180).json()
    f.write_text(json.dumps(js))
    return js


def parse(js, daily):
    """-> long DataFrame site, param, ts(str), value, qual."""
    rows = []
    for t in js["value"]["timeSeries"]:
        _, site, param, _stat = t["name"].split(":")
        for blk in t["values"]:
            for v in blk["value"]:
                val = float(v["value"]) if v["value"] not in ("", None) else np.nan
                if val == NODATA:
                    val = np.nan
                rows.append((site, param, v["dateTime"], val, ",".join(v.get("qualifiers", [])),
                             blk["method"][0]["methodID"] if blk["method"] else None))
    df = pd.DataFrame(rows, columns=["site", "param", "ts", "value", "qual", "method"])
    if daily and len(df):
        df["date"] = pd.to_datetime(df.ts.str[:10]).dt.date
    return df


def get_dv():
    frames = []
    wy = START.year + 1
    while dt.date(wy - 1, 10, 1) <= LAST_FULL:
        a, b = dt.date(wy - 1, 10, 1), min(dt.date(wy, 9, 30), TODAY)
        current = b >= TODAY - dt.timedelta(days=400)  # provisional period: refresh
        js = fetch(DV, {"format": "json", "sites": ",".join(SITES), "parameterCd": ",".join(PARAMS),
                        "statCd": "00003", "startDT": a.isoformat(), "endDT": b.isoformat(), "siteStatus": "all"},
                   f"dv_wy{wy}.json", refresh=current)
        frames.append(parse(js, daily=True))
        wy += 1
    dv = pd.concat(frames, ignore_index=True)
    # More than one time series per site/param (e.g. a second method) would create duplicates: report & keep first
    nmeth = dv.groupby(["site", "param"]).method.nunique()
    if (nmeth > 1).any():
        print("WARNING multiple dv methods:", nmeth[nmeth > 1].to_dict())
    dv = dv.dropna(subset=["value"]).drop_duplicates(["site", "param", "date"])
    return dv


def get_iv():
    a = TODAY - dt.timedelta(days=IV_DAYS)
    js = fetch(IV, {"format": "json", "sites": ",".join(SITES), "parameterCd": ",".join(PARAMS),
                    "startDT": a.isoformat(), "endDT": TODAY.isoformat(), "siteStatus": "all"},
               f"iv_last{IV_DAYS}d.json", refresh=True)
    iv = parse(js, daily=False)
    iv = iv.dropna(subset=["value"])
    # NWIS daily values use local STANDARD time (CST = UTC-6) all year, so group IV by CST date (not clock time)
    iv["date"] = (pd.to_datetime(iv.ts, utc=True) - pd.Timedelta(hours=6)).dt.date
    iv = iv.drop_duplicates(["site", "param", "ts"])
    g = iv.groupby(["site", "param", "date"])
    out = g.value.mean().to_frame("value")
    out["n"] = g.size()
    out["qual"] = g.qual.agg(lambda s: ",".join(sorted(set(",".join(s).split(",")) - {""})))
    out = out.reset_index()
    return out


def main():
    dv = get_dv()
    print(f"dv rows: {len(dv):,}  ({dv.date.min()}..{dv.date.max()})")
    iv = get_iv()
    iv_ok = iv[(iv.n >= IV_MIN_READINGS) & (iv.date <= LAST_FULL)]
    print(f"iv daily aggregates: {len(iv)}, with >= {IV_MIN_READINGS} readings: {len(iv_ok)}")

    dates = pd.date_range(START, LAST_FULL, freq="D").date
    out = []
    for site in SITES:
        d = pd.DataFrame({"site": site, "date": dates})
        for p, nm in PARAMS.items():
            s = dv[(dv.site == site) & (dv.param == p)].set_index("date")
            col = "no3_mgL" if nm == "no3" else "q_cfs"
            d[col] = d.date.map(s.value)
            d[f"{nm}_qual"] = d.date.map(s.qual)
            d[f"{nm}_src"] = np.where(d[col].notna(), "dv", None)
            # IV fill for recent missing days
            si = iv_ok[(iv_ok.site == site) & (iv_ok.param == p)].set_index("date")
            fill = d[col].isna() & d.date.isin(si.index)
            d.loc[fill, col] = d.loc[fill, "date"].map(si.value).round(2 if nm == "no3" else 0)
            d.loc[fill, f"{nm}_qual"] = d.loc[fill, "date"].map(si.qual)
            d.loc[fill, f"{nm}_src"] = "iv"
            print(f"{site} {p}: dv {int((d[f'{nm}_src'] == 'dv').sum())} days, iv-filled {int(fill.sum())} days")
        out.append(d)
    df = pd.concat(out, ignore_index=True)
    df["load_kgN_day"] = df.no3_mgL * df.q_cfs * CFS_MGL_TO_KG_DAY
    df["src"] = df.no3_src  # contract field: source of the nitrate value ('dv' / 'iv' / None)
    df = df[["site", "date", "no3_mgL", "no3_qual", "q_cfs", "q_qual", "load_kgN_day", "src", "no3_src", "q_src"]]
    df.to_parquet(PROC / "nwis_daily.parquet", compression="zstd", index=False)
    report(df)


def report(df):
    df = df.copy()
    df["year"] = pd.to_datetime(df.date).dt.year
    print(f"\nnwis_daily.parquet: {len(df):,} rows, {df.date.min()}..{df.date.max()}")
    for site in SITES:
        s = df[df.site == site]
        print(f"  {site} last nitrate {s.dropna(subset=['no3_mgL']).date.max()}, "
              f"last flow {s.dropna(subset=['q_cfs']).date.max()}")
    cov = df.groupby(["site", "year"]).agg(n=("date", "size"), no3=("no3_mgL", lambda x: x.notna().mean() * 100),
                                           q=("q_cfs", lambda x: x.notna().mean() * 100),
                                           over10=("no3_mgL", lambda x: int((x > MCL).sum())),
                                           no3_max=("no3_mgL", "max"), q_max=("q_cfs", "max"))
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print("\nCoverage % / days > 10 mg/L / max by site-year:")
        print(cov.round(1).to_string())
    for site in SITES:
        s = df[df.site == site]
        i = s.no3_mgL.idxmax()
        print(f"  {site} max nitrate {s.no3_mgL.max()} on {s.loc[i, 'date']}; max flow {s.q_cfs.max():,.0f} cfs")
    q = df[(df.site == "05484500") & (df.date == dt.date(2025, 6, 1))]
    v = float(q.no3_mgL.iloc[0])
    print(f"Sanity: 2025-06-01 Raccoon nitrate = {v} mg/L (expect 12.7)")
    if abs(v - 12.7) > 0.05:
        sys.exit("SANITY FAIL")
    print("src counts:", df.groupby(["site", "src"]).size().to_dict())


if __name__ == "__main__":
    main()
