"""Agreement between HLS (30 m, field cells) and MODIS 13Q1 (250 m, row-crop pixels) living-cover share in the
focus HUC-12s.

MODIS: data/processed/cover_huc12_8day.parquet (modis module; `date` = composite start + 8 d; each 16-day composite
covers [date - 8, date + 8)). HLS: data/processed/hls_field_ts.parquet clear observations of the field cells.
For every focus HUC-12 and MODIS composite, the HLS living share = share of clear field observations inside the
composite window whose cell-median NDVI >= 0.30 (live_px_share >= 0.5); paired when >= 30 HLS field observations
and MODIS valid_frac >= 0.5. Also pairs at the whole-focus level, and mean NDVI (HLS cell-mean vs MODIS mean).
Expected bias: MODIS composites keep the max-NDVI day of 16 (MVC), and 250 m row-crop pixels include field edges,
so MODIS should read greener than HLS, mostly in the shoulder seasons.

Beyond the pooled r (dominated by the shared seasonal cycle) it reports: the deseasonalized r (both series minus
their all-HUC mean for the calendar month), Mar-May r and bias, and HUC-12 ranking agreement (Pearson/Spearman r of
the 10 HUC-12 Apr-May means, and the median per-composite Spearman across HUC-12s for Apr-May composites with >= 5
HUC-12s paired).

Output: data/processed/hls_vs_modis.json. If the MODIS file is missing it writes a 'skipped' note (rerun later).
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import PROC
from fields_common import load_focus

OUT = PROC / "hls_vs_modis.json"
MIN_HLS = 30
MIN_VALID = 0.5


def stats(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return dict(n=int(len(a)))
    return dict(n=int(len(a)), r=round(float(np.corrcoef(a, b)[0, 1]), 3),
                bias_modis_minus_hls=round(float(np.mean(b - a)), 3),
                mae=round(float(np.mean(np.abs(b - a))), 3), rmse=round(float(np.sqrt(np.mean((b - a) ** 2))), 3),
                agree_class_pct=round(float(100 * np.mean((a >= 0.5) == (b >= 0.5))), 1))


def main():
    mp = PROC / "cover_huc12_8day.parquet"
    if not mp.exists():
        OUT.write_text(json.dumps({"status": "skipped", "note": "cover_huc12_8day.parquet (modis module) not present "
                                   "yet; rerun python3 pipeline/p13_hls_vs_modis.py"}, indent=1))
        print("MODIS file missing: wrote skipped note")
        return
    foc = load_focus()
    m = pd.read_parquet(mp)
    m = m[m.huc12.isin(foc["huc12s"])].copy()
    m["date"] = pd.to_datetime(m.date)
    m["w0"] = m.date - pd.Timedelta(days=8)
    m["w1"] = m.date + pd.Timedelta(days=8)
    ts = pd.read_parquet(PROC / "hls_field_ts.parquet")
    ts = ts[ts.clear].copy()
    ts["field_id"] = ts.field_id.astype(str)
    f = pd.read_parquet(PROC / "fields.parquet", columns=["field_id", "huc12"])
    ts = ts.merge(f, on="field_id")
    ts["date"] = pd.to_datetime(ts.date)
    ts["live"] = (ts.live_px_share >= 0.5).astype(float)
    m = m[(m.date >= ts.date.min()) & (m.date <= ts.date.max())]

    rows = []
    for h, mh in m.groupby("huc12"):
        th = ts[ts.huc12 == h].sort_values("date")
        dn = th.date.values
        for r in mh.itertuples():
            i0, i1 = np.searchsorted(dn, np.datetime64(r.w0)), np.searchsorted(dn, np.datetime64(r.w1))
            if i1 - i0 < MIN_HLS or not (r.valid_frac >= MIN_VALID):
                continue
            s = th.iloc[i0:i1]
            rows.append(dict(huc12=h, date=r.date, sensor=r.sensor, hls_live=s.live.mean(), hls_ndvi=s.ndvi.mean(),
                             n_hls=i1 - i0, n_hls_dates=s.date.nunique(), modis_live=r.living_share,
                             modis_ndvi=r.mean_ndvi, modis_valid=r.valid_frac))
    P = pd.DataFrame(rows)
    if P.empty:
        OUT.write_text(json.dumps({"status": "no_pairs"}, indent=1))
        print("no pairs")
        return
    P["month"] = P.date.dt.month
    season = P.month.map({12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM", 6: "JJA", 7: "JJA", 8: "JJA",
                          9: "SON", 10: "SON", 11: "SON"})
    out = dict(status="ok", method=__doc__.strip().split("\n\n")[1].replace("\n", " "),
               hls_through=str(ts.date.max().date()), modis_through=str(m.date.max().date()),
               focus_huc12s=foc["huc12s"], min_hls_obs=MIN_HLS, min_modis_valid_frac=MIN_VALID,
               living_share=stats(P.hls_live, P.modis_live), mean_ndvi=stats(P.hls_ndvi, P.modis_ndvi),
               by_season={k: stats(g.hls_live, g.modis_live) for k, g in P.groupby(season)},
               by_huc12={k: stats(g.hls_live, g.modis_live) for k, g in P.groupby("huc12")})
    # whole focus area: pool HUC-12s per composite (weighted by HLS obs)
    agg = P.groupby(["date", "sensor"]).apply(
        lambda g: pd.Series(dict(hls=np.average(g.hls_live, weights=g.n_hls), modis=g.modis_live.mean())),
        include_groups=False).reset_index()
    out["focus_level"] = stats(agg.hls, agg.modis)
    # spring (Mar 15 - May 10) and fall (Oct 15 - Dec 15) windows, where the leak calendar matters most
    doy = P.date.dt.dayofyear
    out["spring_window"] = stats(P.hls_live[(doy >= 74) & (doy <= 130)], P.modis_live[(doy >= 74) & (doy <= 130)])
    out["fall_window"] = stats(P.hls_live[(doy >= 288) & (doy <= 349)], P.modis_live[(doy >= 288) & (doy <= 349)])
    # seasonality removed: anomalies from the all-HUC monthly means
    clim = P.groupby("month")[["hls_live", "modis_live"]].transform("mean")
    out["deseasonalized"] = stats(P.hls_live - clim.hls_live, P.modis_live - clim.modis_live)
    out["deseasonalized"].pop("agree_class_pct", None)
    mam = P.month.between(3, 5)
    out["mar_may"] = stats(P.hls_live[mam], P.modis_live[mam])
    # HUC-12 ranking agreement in Apr-May (the spring leak window)
    am = P[P.month.between(4, 5)]
    hm = am.groupby("huc12")[["hls_live", "modis_live"]].mean()
    per = []
    for _, g in am.groupby(["date", "sensor"]):
        if len(g) >= 5 and g.hls_live.nunique() > 1 and g.modis_live.nunique() > 1:
            per.append(spearmanr(g.hls_live, g.modis_live).statistic)
    per = np.array(per, float)
    out["huc12_ranking_apr_may"] = dict(
        n_huc12=int(len(hm)), pearson_r_huc_means=round(float(np.corrcoef(hm.hls_live, hm.modis_live)[0, 1]), 3),
        spearman_r_huc_means=round(float(spearmanr(hm.hls_live, hm.modis_live).statistic), 3),
        n_composites=int(np.isfinite(per).sum()), per_composite_spearman_median=round(float(np.nanmedian(per)), 3),
        per_composite_spearman_mean=round(float(np.nanmean(per)), 3),
        huc_means={k: dict(hls=round(float(v.hls_live), 3), modis=round(float(v.modis_live), 3))
                   for k, v in hm.iterrows()},
        hls_range=[round(float(hm.hls_live.min()), 3), round(float(hm.hls_live.max()), 3)],
        modis_range=[round(float(hm.modis_live.min()), 3), round(float(hm.modis_live.max()), 3)])
    hr = out["huc12_ranking_apr_may"]
    out["conclusion"] = (
        f"MODIS ranks HUC-12s well in spring (Apr-May HUC-12 means r = {hr['pearson_r_huc_means']}, Spearman "
        f"{hr['spearman_r_huc_means']}; per-composite Spearman median {hr['per_composite_spearman_median']}) but "
        f"overstates the spring living share in absolute terms (Apr-May HUC-12 means MODIS "
        f"{hr['modis_range'][0]:.2f}-{hr['modis_range'][1]:.2f} vs HLS {hr['hls_range'][0]:.2f}-"
        f"{hr['hls_range'][1]:.2f}; Mar-May r = {out['mar_may'].get('r')}, bias {out['mar_may'].get('bias_modis_minus_hls'):+}). "
        f"The pooled r ({out['living_share'].get('r')}) is mostly the shared seasonal cycle; deseasonalized r = "
        f"{out['deseasonalized'].get('r')}. Use MODIS as a relative (ranking) index across HUC-12s and HLS for the "
        f"absolute field-level bare share.")
    mon = P.groupby("month")[["hls_live", "modis_live"]].mean().round(3)
    out["monthly_mean_living_share"] = {int(k): dict(hls=float(v.hls_live), modis=float(v.modis_live))
                                        for k, v in mon.iterrows()}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("living_share", "mean_ndvi", "focus_level", "by_season", "spring_window",
                                          "fall_window", "deseasonalized", "mar_may")}, indent=1))
    print(json.dumps({k: v for k, v in out["huc12_ranking_apr_may"].items() if k != "huc_means"}))
    print(out["conclusion"])
    print(mon.to_string())


if __name__ == "__main__":
    main()
