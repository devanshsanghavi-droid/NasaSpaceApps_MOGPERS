#!/usr/bin/env python3
"""m08_export_web.py: write the web data contract (web/data/*) from model/out/* and docs/facts.json.

Run (from apps/field-to-faucet/):  python3 model/m08_export_web.py      (~10 s, no network)
Run order: m02/m03/m04 (river), m05/m06 (fields), m07 (scenarios), then this. Re-runnable end to end.

Writes (web/data/): river_series.json, validation.json, outlook.json, scenarios.json, fields.geojson,
field_detail/<huc12>.json, field_index.json, strategies.json, huc12.geojson (existing outlines + props from
model/out/huc12_props.json), facts.json (web copy with alias keys), meta.json.
Never writes basins.geojson, sites.json, rivers.geojson, counties.geojson, places.json (data modules own them).

Display model: metrics.json "display_model" if present (default "v1" = the GBM in river_daily.parquet p10/p50/p90).
"""
from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
PROC = APP / "data" / "processed"
OUT = APP / "model" / "out"
WEB = APP / "web" / "data"
FACTS = APP / "docs" / "facts.json"
SITES = ["05484500", "05482000"]
PROTECTED = {"basins.geojson", "sites.json", "rivers.geojson", "counties.geojson", "places.json"}
SERIES_START = "2016-01-01"
MAX_TOTAL_MB = 15.0

# frontend keys (web/js/city.js, notes/frontend.md) -> facts.json ids
FACT_ALIASES = {
    "people_served": "water_people_served",
    "plant_days_2025": "plant_days_2025",
    "plant_days_2026": "plant_days_2026",
    "plant_cost_2025_usd": "plant_cost_2025_usd",
    "plant_om_cost_2025_usd": "plant_om_cost_2025_usd",
    "ban_days_2025": "ban_2025_days",
    "ban_days_2026": "ban_2026_days",
    "fert_price_usd_lb_N": "fert_price_usd_lbN",
    "plant_cost_per_day_usd": "plant_cost_per_day_usd",
    "mcl_mgL": "mcl_mgL",
}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sig(x, n=3):
    """Round to n significant digits; None for NaN/inf."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    if not math.isfinite(x):
        return None
    if x == 0:
        return 0
    v = float(f"{x:.{n}g}")
    return int(v) if v.is_integer() and abs(v) >= 1 else v


def rnd(o, n=3):
    """Recursively round floats in a JSON-like object."""
    if isinstance(o, float):
        return sig(o, n)
    if isinstance(o, dict):
        return {k: rnd(v, n) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [rnd(v, n) for v in o]
    if isinstance(o, (np.floating,)):
        return sig(float(o), n)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def write(name: str, obj, compact=True):
    assert name.split("/")[0] not in PROTECTED, name
    p = WEB / name
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(obj, separators=(",", ":") if compact else None, allow_nan=False, ensure_ascii=False)
    p.write_text(txt)
    return p.stat().st_size


def arr(s: pd.Series, nd=2):
    return [None if not np.isfinite(v) else round(float(v), nd) for v in s.to_numpy(float)]


# ----------------------------------------------------------------------------- display model resolution
def display_model(metrics) -> dict:
    """Per-site display model. metrics.json "display_model" may be a string ("v1"/"v2") or the v2 run's dict
    {sites: {<site>: {model: "v1"|"v2", ...}}, ...}. Default v1."""
    dm = metrics.get("display_model", "v1")
    out = {}
    for site in SITES:
        if isinstance(dm, str):
            out[site] = dm
        elif isinstance(dm, dict):
            out[site] = str(dm.get("sites", {}).get(site, {}).get("model", dm.get("model", "v1")))
        else:
            out[site] = "v1"
    return out


V2_FILE = OUT / "v2" / "river_daily_v2.parquet"


def river_frame(site: str, model: str) -> tuple[pd.DataFrame, dict]:
    """One site's daily rows with p10/p50/p90 of the requested model (v2 file: columns p10/p50/p90 are v2)."""
    if model == "v2" and V2_FILE.exists():
        rd = pd.read_parquet(V2_FILE)
        rd["date"] = pd.to_datetime(rd["date"])
        rd = rd[rd["site"] == site]
        if len(rd) and rd[["p10", "p50", "p90"]].notna().any().all():
            v1 = pd.read_parquet(OUT / "river_daily.parquet")
            v1["date"] = pd.to_datetime(v1["date"])
            v1 = v1[v1["site"] == site].set_index("date")
            if "reservoir_p50" in v1.columns:
                rd["reservoir_p50"] = rd["date"].map(v1["reservoir_p50"])
            return rd, dict(model="v2", file="model/out/v2/river_daily_v2.parquet")
    rd = pd.read_parquet(OUT / "river_daily.parquet")
    rd["date"] = pd.to_datetime(rd["date"])
    note = None if model == "v1" else f"display model {model} output not found; showing v1"
    return rd[rd["site"] == site], dict(model="v1", file="model/out/river_daily.parquet", note=note)


# ----------------------------------------------------------------------------- river_series.json
def export_river_series(metrics, dm):
    frames = {site: river_frame(site, dm[site]) for site in SITES}
    end = max(f[0]["date"].max() for f in frames.values())
    sp = metrics.get("splits", {})
    split = {k: [v[0], v[1] or str(end.date())] for k, v in sp.items()}
    out = dict(mcl=metrics.get("mcl_mgL", 10.0), display_model=dm,
               model_label=("drivers-only simulation (NASA POWER weather and soil wetness, MODIS/HLS cover, CDL, "
                            "USGS flow; never sees measured nitrate)"),
               split=split, sites={})
    idx = pd.date_range(SERIES_START, end, freq="D")
    for site in SITES:
        rd, desc = frames[site]
        g = rd.set_index("date").sort_index()
        g = g[~g.index.duplicated()].reindex(idx)
        s = dict(name=metrics["sites"].get(site, {}).get("name", site), model=desc,
                 dates=[str(d.date()) for d in idx], obs=arr(g["obs"]), q_cfs=[sig(v) for v in g["q_cfs"]],
                 p10=arr(g["p10"]), p50=arr(g["p50"]), p90=arr(g["p90"]))
        if "reservoir_p50" in g.columns:
            s["reservoir_p50"] = arr(g["reservoir_p50"])
        if "no3_qual" in g.columns:
            q = g["no3_qual"].astype(str)
            prov = q.str.contains("P", na=False)
            s["provisional_from"] = str(idx[np.argmax(prov.to_numpy())].date()) if prov.any() else None
        out["sites"][site] = s
    return write("river_series.json", out), str(end.date())


# ----------------------------------------------------------------------------- validation.json
KEEP = ("NSE", "KGE", "RMSE", "MAE", "bias", "pbias_pct", "r", "coverage80", "n")


def model_metrics(m):
    o = {k: m.get(k) for k in KEEP if k in m}
    ex = m.get("exceed10") or {}
    if ex:
        o.update(hit_rate=ex.get("hit_rate"), false_alarm=ex.get("false_alarm_ratio"), CSI=ex.get("csi"),
                 obs_days_over10=ex.get("obs_days"), pred_days_over10=ex.get("pred_days"))
    return o


def export_validation(metrics, dm, scen):
    sites_out = {}
    extra = metrics.get("v2", {}).get("sites", {}) if isinstance(metrics.get("v2"), dict) else {}
    for site in SITES:
        s = metrics["sites"].get(site)
        if not s:
            continue
        by_split = {}
        for split, models in s.get("splits", {}).items():
            mm = {}
            for name, m in models.items():
                if not isinstance(m, dict) or "NSE" not in m:
                    continue
                if split == "train" and name == "gbm" and "gbm_loyo_cv" in models:
                    continue  # in-sample fit is meaningless; show the leave-one-year-out CV instead
                key = "gbm" if (split == "train" and name == "gbm_loyo_cv") else name
                mm[key] = model_metrics(m)
            v2s = extra.get(site, {}).get("splits", {}).get(split, {})
            v2key = "gbm_v2_loyo_cv" if (split == "train" and "gbm_v2_loyo_cv" in v2s) else "gbm_v2"
            if isinstance(v2s.get(v2key), dict) and "NSE" in v2s[v2key]:
                mm["gbm_v2"] = model_metrics(v2s[v2key])
            by_split[split] = mm
        cr = s.get("crisis_2025", {})
        lv = s.get("live_2026", {})
        sites_out[site] = dict(
            name=s.get("name", site), by_split=by_split,
            test_by_year={y: {k: model_metrics(v) for k, v in d.items() if isinstance(v, dict)} for y, d in s.get("test_by_year", {}).items()},
            crisis_2025={k: {kk: v.get(kk) for kk in ("obs_days_over10", "pred_days_over10_on_obs_days", "p90_days_over10_on_obs_days", "obs_peak", "obs_peak_date", "pred_peak", "pred_peak_date")} for k, v in cr.items() if isinstance(v, dict)},
            live_2026={k: {kk: v.get(kk) for kk in ("obs_days_over10", "pred_days_over10_on_obs_days", "p90_days_over10_on_obs_days", "obs_peak", "obs_peak_date")} for k, v in lv.items() if isinstance(v, dict)},
            level_ratio_obs_over_model={y: (v.get("ratio_obs_over_pred") if isinstance(v, dict) else None) for y, v in s.get("residual_diagnostics", {}).get("by_year", {}).items()},
            days_over10_by_year=s.get("by_year_days_over10"),
            display_model=dm.get(site, "v1"))
        e2 = extra.get(site)
        if e2:
            c2 = e2.get("crisis_2025", {}).get("gbm_v2", {})
            l2 = e2.get("live_2026", {}).get("gbm_v2", {})
            st = e2.get("strict_check", {}).get("2020_2025", {})
            sites_out[site]["v2"] = dict(
                label=e2.get("labels", {}).get("test", "post-hoc"),
                what=("v1 plus a causal nitrogen carry-over store (prior seasons' rain and drought), designed after "
                      "seeing the v1 2025 miss"),
                crisis_2025={kk: c2.get(kk) for kk in ("obs_days_over10", "pred_days_over10_on_obs_days", "p90_days_over10_on_obs_days", "pred_peak")},
                live_2026={kk: l2.get(kk) for kk in ("obs_days_over10", "pred_days_over10_on_obs_days", "p90_days_over10_on_obs_days")},
                strict_check_2020_2025={k: {kk: v.get(kk) for kk in ("rmse_log", "NSE", "KGE", "bias")} for k, v in st.items() if isinstance(v, dict)},
                strict_train_years=e2.get("strict_check", {}).get("train_years"),
                blind_2013=e2.get("blind_2013"))
    # plain-language lines, built from the numbers
    r, d = metrics["sites"]["05484500"], metrics["sites"]["05482000"]
    tr, td = r["splits"]["test"], d["splits"]["test"]
    rat = r.get("residual_diagnostics", {}).get("by_year", {})
    ratd = d.get("residual_diagnostics", {}).get("by_year", {})
    cr, crd = r.get("crisis_2025", {}).get("gbm", {}), d.get("crisis_2025", {}).get("gbm", {})
    lines = [
        (f"Fair test: {'the first version of the model (v1)' if 'v2' in dm.values() else 'the model'} learned from 2016-2022 and was scored on 2023-2025, years it never saw. It captures about "
         f"{tr['gbm']['NSE']:.0%} of the day-to-day ups and downs of nitrate at the Raccoon River gauge at Van Meter, upstream of the intake (NSE {tr['gbm']['NSE']:.2f}) and "
         f"{td['gbm']['NSE']:.0%} at the Des Moines River (NSE {td['gbm']['NSE']:.2f}), against {tr['climatology']['NSE']:.2f} and "
         f"{td['climatology']['NSE']:.2f} for 'the usual level for that date'."),
        (f"It never sees measured nitrate, only NASA weather and soil wetness, satellite cover, crops and river flow. "
         f"Persistence ('same as 7 days ago') scores higher ({tr['persistence_7d']['NSE']:.2f}), but it needs last week's "
         f"measurement, so it is a forecast, not an explanation."),
    ]
    if cr:
        lines.append(
            f"Honest miss: in 2025 the Raccoon ran above 10 mg/L on {cr.get('obs_days_over10')} measured days; the {'v1' if 'v2' in dm.values() else ''} model's "
            f"middle estimate gave {cr.get('pred_days_over10_on_obs_days')}, although its upper 8-in-10 bound was above 10 mg/L on "
            f"{cr.get('p90_days_over10_on_obs_days')} measured days (plausible, not expected). At the Des Moines River: {crd.get('obs_days_over10')} measured vs "
            f"{crd.get('pred_days_over10_on_obs_days')} modelled.")
    if "2025" in rat:
        lines.append(
            f"Why: from early 2025 the rivers carried about {rat['2025']['ratio_obs_over_pred']:.1f}x (Raccoon) and "
            f"{ratd.get('2025', {}).get('ratio_obs_over_pred', float('nan')):.1f}x (Des Moines) the nitrate that that year's "
            f"weather, wet soil and bare ground explain, in every season and at low and high flow. Years after droughts run "
            f"high (2022 and 2024 too), consistent with one hypothesis, nitrate left in soils and groundwater after the 2020-2023 drought (not proven: 2023 ran low right after the 2022 drought; fertilizer, groundwater lag or a rain-data shift could also contribute), "
            f"a slow store the model has no input for. The 2025 data are USGS-approved, so it is not a sensor artifact.")
    for site, nm in (("05484500", "Raccoon"), ("05482000", "Des Moines")):
        e2 = sites_out.get(site, {}).get("v2")
        if not e2 or not e2.get("crisis_2025", {}).get("obs_days_over10"):
            continue
        c2 = e2["crisis_2025"]
        b13 = e2.get("blind_2013") or {}
        txt = (f"{nm}: a second version (v2) adds a nitrogen carry-over store for the years after a drought. It was "
               f"built after seeing the 2025 miss, so its 2023-2025 score is not a clean test. 2025 days above 10 mg/L: "
               f"measured {c2['obs_days_over10']}, v2 {c2['pred_days_over10_on_obs_days']}"
               f"{', v1 ' + str(sites_out[site]['crisis_2025'].get('gbm', {}).get('pred_days_over10_on_obs_days')) if sites_out[site]['crisis_2025'].get('gbm') else ''}.")
        if b13.get("v2"):
            txt += (f" Pre-registered blind check on 2013 (the flush after the 2012 drought, held out): measured "
                    f"{b13.get('obs_days_over10')} days above 10, v2 {b13['v2'].get('pred_days_over10')}, v1 features "
                    f"{b13.get('v1_features', {}).get('pred_days_over10')}.")
        txt += (f" The chart shows {'v2' if dm.get(site) == 'v2' else 'v1'} here (display rule fixed before any v2 2026 "
                f"metric was computed; v1's 2026 miss was already known).")
        lines.append(txt)
    lines.append(
        "So the app uses the model for what it does well: RELATIVE what-if changes (less bare soil), applied to the "
        "measured river, never its absolute 2025 level. Near-term levels come from the 14-day outlook, which starts "
        "from the latest measurement.")
    cov = tr["gbm"].get("coverage80")
    if cov is not None:
        lines.append(f"The 8-in-10 band held the measured value on {cov:.0%} of test days (it should be 80%): ranges are "
                     f"somewhat too narrow in new conditions.")
    ol = metrics.get("outlook", {}).get("sites", {}).get("05484500", {})
    try:
        h7 = ol["test_2023_2025"]["h7"]["gbm"]["skill_vs_persistence_mse"]
        h14 = ol["test_2023_2025"]["h14"]["gbm"]["skill_vs_persistence_mse"]
        lines.append(f"14-day outlook: on 2023-2025 it beat 'no change' by {h7:.0%} at one week and {h14:.0%} at two "
                     f"weeks (squared error, Raccoon). It uses no weather forecast, so a big storm can push nitrate "
                     f"outside its range.")
    except (KeyError, TypeError):
        pass
    if scen:
        pc = scen["thresholds"]["calibration"]["plant"]
        lines.append(
            f"Removal-plant proxy (the utility's rules are not public): '{pc['rule']}'. Fitted to 2025 "
            f"({pc['fit_2025']['pred_days']} proxy days vs {pc['fit_2025']['true_days']} reported); tested on 2026 without "
            f"refitting: {pc['test_2026_jan_jul']['pred_days']} vs {pc['test_2026_jan_jul']['true_days']} days "
            f"(daily agreement F1 {pc['test_2026_jan_jul']['f1']}).")
    crisis_text = lines[2] + " " + lines[3] if len(lines) > 3 and cr else ""
    out = dict(display_model=dm, splits={k: [v[0], v[1]] for k, v in metrics.get("splits", {}).items()},
               notes=metrics.get("notes", []), sites=sites_out, lines=lines, crisis_2025=dict(text=crisis_text),
               outlook_skill={site: metrics.get("outlook", {}).get("sites", {}).get(site, {}).get("test_2023_2025") for site in SITES})
    if extra:
        out["v2_present"] = True
    return write("validation.json", rnd(out, 3))


# ----------------------------------------------------------------------------- facts.json (web copy)
def export_facts():
    src = json.loads(FACTS.read_text())
    facts = {}
    for f in src["facts"]:
        if f.get("verification") == "unverified":
            continue
        rec = dict(value=f.get("value"), unit=f.get("unit"), label=f.get("claim"),
                   source=f.get("publisher") or f.get("source_title"), source_title=f.get("source_title"),
                   url=f.get("url"), verification=f.get("verification"),
                   verified=f.get("verification") in ("primary", "derived"), source_kind=f.get("source_kind"),
                   range=f.get("range"), year=f.get("year"),
                   date_published=f.get("date_published"), quote=f.get("quote"), id=f["id"])
        if "inrs_2024_update" in f:
            rec["inrs_2024_update"] = f["inrs_2024_update"]
        facts[f["id"]] = rec
    aliases = {}
    for k, fid in FACT_ALIASES.items():
        if fid in facts:
            if k != fid:
                facts[k] = dict(facts[fid], alias_of=fid)
            aliases[k] = fid
    out = dict(generated_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), source_file="docs/facts.json",
               checked=src.get("generated_at"), verification_levels=src.get("verification_levels"),
               note=("Web copy of docs/facts.json (unverified facts dropped). Alias keys used by the app point to the "
                     "original ids (alias_of). Show the source link with every number."),
               aliases=aliases, facts=facts)
    return write("facts.json", out)


# ----------------------------------------------------------------------------- huc12.geojson
def export_huc12():
    p = WEB / "huc12.geojson"
    g = json.loads(p.read_text())
    props = json.loads((OUT / "huc12_props.json").read_text())
    keys = ["leak_index", "share_of_basin_leak", "rank", "row_crop_share", "poorly_drained_share", "bare_days_wet",
            "in_focus", "lbN_ac_yr", "share_of_basin_leak_recent", "n_in_basin"]
    n = 0
    for f in g["features"]:
        pr = props.get(f["properties"].get("huc12"))
        if not pr:
            continue
        for k in keys:
            if k in pr:
                f["properties"][k] = pr[k]
        n += 1
        if isinstance(f["properties"].get("area_km2"), float):
            f["properties"]["area_km2"] = round(f["properties"]["area_km2"], 2)
    p.write_text(json.dumps(g, separators=(",", ":"), allow_nan=False))
    return p.stat().st_size, n, len(g["features"])


# ----------------------------------------------------------------------------- fields + detail
def export_fields():
    shutil.copyfile(OUT / "fields.geojson", WEB / "fields.geojson")
    fg = json.loads((OUT / "fields.geojson").read_text())
    index = {f["properties"]["field_id"]: f["properties"]["huc12"] for f in fg["features"]}
    dst = WEB / "field_detail"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    tot = 0
    for p in sorted((OUT / "field_detail").glob("*.json")):
        d = json.loads(p.read_text())
        tot += write(f"field_detail/{p.name}", rnd(d, 3))
    if (WEB / "field_detail.json").exists():
        (WEB / "field_detail.json").unlink()   # split files only (frontend prefers a single file when present)
    write("field_index.json", index)
    return len(fg["features"]), tot


# ----------------------------------------------------------------------------- meta.json
def max_date(path, col="date", filt=None):
    try:
        df = pd.read_parquet(path, columns=None if filt else [col])
        if filt:
            df = filt(df)
        return str(pd.to_datetime(df[col]).max().date())
    except Exception as ex:  # noqa: BLE001
        return f"unavailable ({type(ex).__name__})"


def export_meta(dm, river_end, scen, sizes):
    pw = pd.read_parquet(PROC / "power_daily_basin.parquet", columns=["date", "PRECTOTCORR"]).dropna()
    modis = max_date(PROC / "cover_basin_8day.parquet", filt=lambda d: d[d.get("gapfill_src", pd.Series("modis", index=d.index)).fillna("modis") == "modis"])
    cdl = int(pd.read_parquet(PROC / "cdl_basin_year.parquet", columns=["year"])["year"].max())
    sources = [
        dict(name="NASA HLS v2.0 (Harmonized Landsat Sentinel-2, L30 + S30)", nasa=True,
             role="Field-level living cover vs bare soil (400 m fields, focus area, 2020-2026); fills the Jul-Nov 2025 MODIS gap",
             url="https://planetarycomputer.microsoft.com/dataset/hls2-l30"),
        dict(name="NASA MODIS Terra/Aqua 13Q1 NDVI (MOD13Q1/MYD13Q1 v6.1)", nasa=True,
             role="Bare-soil share of row-crop land per basin and HUC-12 (river-model driver, hotspot index, scenario lever)",
             url="https://lpdaac.usgs.gov/products/mod13q1v061/"),
        dict(name="NASA POWER daily (MERRA-2 / GEOS-IT)", nasa=True,
             role="Rain, root-zone soil wetness (GWETROOT), snow and temperature: drainage and river-model drivers, field leak calendar",
             url="https://power.larc.nasa.gov/"),
        dict(name="NASA GPM IMERG (V06 half-hourly)", nasa=True,
             role="Storm-intensity check of POWER rain on sampled storm days, 2016-2021",
             url="https://gpm.nasa.gov/data/imerg"),
        dict(name="NASADEM elevation", nasa=True, role="Field and HUC-12 slope",
             url="https://planetarycomputer.microsoft.com/dataset/nasadem"),
        dict(name="USGS NWIS (sites 05484500, 05482000; nitrate 99133, flow 00060)", nasa=False,
             role="Measured nitrate and flow: validation target, loads, and the observed series the scenarios change",
             url="https://waterdata.usgs.gov/monitoring-location/05484500/"),
        dict(name="USDA NASS Cropland Data Layer", nasa=False, role="Row-crop masks, crop sequences, basin crop shares",
             url="https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php"),
        dict(name="USDA NRCS SSURGO (Soil Data Access)", nasa=False, role="Drainage class (poorly drained = tile-drained)",
             url="https://sdmdataaccess.sc.egov.usda.gov/"),
        dict(name="USGS Watershed Boundary Dataset and NHD", nasa=False, role="Basins, HUC-12s, rivers",
             url="https://hydro.nationalmap.gov/"),
        dict(name="US Census TIGER/Gazetteer", nasa=False, role="Counties and places on the maps",
             url="https://www.census.gov/geographies/mapping-files.html"),
        dict(name="Iowa Nutrient Reduction Strategy (2024 practice efficiencies; 2025 edition)", nasa=False,
             role="Trial evidence for practice effects (cereal rye 28%, SD 26) used in scenarios and strategy cards",
             url="https://www.nutrientstrategy.iastate.edu/sites/default/files/documents/INRS_2024_PracticeEffienciesNitrogen_U20240319.pdf"),
        dict(name="Central Iowa Water Works, KCCI, Iowa Public Radio", nasa=False,
             role="Removal-plant days and costs, watering-ban dates, people served (see facts.json)",
             url="https://ciww.gov/what-is-the-nitrate-removal-facility/"),
        dict(name="Iowa State University Extension (AgDM), IDALS", nasa=False, role="Cover-crop costs and cost-share",
             url="https://www.extension.iastate.edu/agdm/"),
    ]
    caveats = [
        "The river model explains normal years well (test NSE about 0.6) but badly misses the 2025-26 level: rivers carried about twice the nitrate the drivers explain, one hypothesis: nitrate left over after the 2020-2023 drought. Scenarios therefore change the MEASURED series by a relative amount; the model's absolute 2025 level is never used for impact counts.",
        "Scenario effects combine Iowa field trials (cereal rye: 28% average cut, SD 26) with the learned river response to less bare soil, which is weakly identified because past cover changes were mostly seasonal. Ranges are 8 in 10 of the simulated outcomes.",
        "Legacy nitrate: a change on fields takes more than one season to show in the river.",
        "Cover-crop adoption is already about 17% of Iowa corn and soybean acres (statewide, secondary source); the slider adds acres on top, assuming adopters are typical fields.",
        "Removal-plant and watering-ban days come from proxy rules fitted to 2025 and tested on 2026; the utility's real decisions also depend on demand and capacity. Cost avoided is operating cost only; capital is not avoided in the short run.",
        "A 'field' is a 400 m grid cell (about 40 acres) that was one row crop in most years; its N rate, manure and tile layout are unknown.",
        "NASA POWER rain is about 50 km resolution and smooths storm peaks; continuous IMERG was not available after May 2021.",
        "MODIS (250 m) bare share is a relative index, not a cover-crop map; Jul-Nov 2025 is filled from HLS.",
        "USGS nitrate data from 2026-06-02 on are provisional. Exceedance days are counted on days with a measurement.",
        "Fertilizer values are upper bounds and the AMS price is a secondary source (ISU budgets N at $0.53/lb).",
    ]
    if scen:
        caveats.append("Plant proxy test on 2026: " + (
            f"{scen['thresholds']['calibration']['plant']['test_2026_jan_jul']['pred_days']} proxy days vs "
            f"{scen['thresholds']['calibration']['plant']['test_2026_jan_jul']['true_days']} reported (Jan-Jul)."))
    meta = dict(
        generated_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), display_model=dm,
        data_through=dict(nwis=max_date(PROC / "nwis_daily.parquet"), power=str(pd.to_datetime(pw["date"]).max().date()),
                          modis=modis, hls=max_date(PROC / "hls_field_ts.parquet"), cdl=str(cdl),
                          model_series=river_end),
        facts_checked="2026-11-14", sources=sources, caveats=caveats,
        files={k: v for k, v in sorted(sizes.items())},
        pipeline=["pipeline/p*.py (data)", "model/m01-m04 (river model, outlook)", "model/m05-m06 (fields, strategies)",
                  "model/m07_scenarios.py", "model/m08_export_web.py"])
    return write("meta.json", meta, compact=False)


def main():
    t0 = time.time()
    WEB.mkdir(parents=True, exist_ok=True)
    metrics = json.loads((OUT / "metrics.json").read_text())
    dm = display_model(metrics)
    scen = json.loads((OUT / "scenarios.json").read_text()) if (OUT / "scenarios.json").exists() else None
    if scen is None:
        log("WARNING model/out/scenarios.json missing: run model/m07_scenarios.py first")
    sizes = {}
    sizes["river_series.json"], river_end = export_river_series(metrics, dm)
    sizes["validation.json"] = export_validation(metrics, dm, scen)
    sizes["outlook.json"] = write("outlook.json", rnd(json.loads((OUT / "outlook.json").read_text()), 4))
    if scen is not None:
        sizes["scenarios.json"] = write("scenarios.json", scen)
    sizes["strategies.json"] = write("strategies.json", rnd(json.loads((OUT / "strategies.json").read_text()), 4))
    nf, sizes["field_detail/"] = export_fields()
    sizes["fields.geojson"] = (WEB / "fields.geojson").stat().st_size
    sizes["field_index.json"] = (WEB / "field_index.json").stat().st_size
    sizes["huc12.geojson"], nh, nh_all = export_huc12()
    sizes["facts.json"] = export_facts()
    sizes["meta.json"] = export_meta(dm, river_end, scen, sizes)
    # --- checks
    total = 0
    bad = []
    for p in sorted(WEB.rglob("*")):
        if p.is_file():
            total += p.stat().st_size
            if p.suffix in (".json", ".geojson"):
                try:
                    json.loads(p.read_text())
                except Exception as ex:  # noqa: BLE001
                    bad.append(f"{p.name}: {ex}")
    log(f"display_model={dm}; fields {nf}; huc12 enriched {nh}/{nh_all}")
    for k, v in sorted(sizes.items()):
        log(f"  {k:22s} {v / 1e3:8.0f} kB")
    log(f"web/data total {total / 1e6:.2f} MB (limit {MAX_TOTAL_MB} MB); parse errors: {bad or 'none'}; {time.time() - t0:.0f} s")
    if total > MAX_TOTAL_MB * 1e6 or bad:
        raise SystemExit("web/data check FAILED")


if __name__ == "__main__":
    main()
