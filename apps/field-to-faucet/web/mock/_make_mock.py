"""Writes MOCK web files into web/mock/ for UI development only.

EVERY NUMBER WRITTEN HERE IS SYNTHETIC. Each file carries "mock": true and a "note".
The app loads web/data/<file> first and only falls back to web/mock/<file> when the real file is
missing (or, for huc12.geojson, when the real file has no leak scores yet), and then shows a red
"MOCK DATA - not real" banner naming the file.

Geometry: huc12.geojson copies the REAL outlines from web/data/huc12.geojson (read-only) and adds
synthetic scores. Rivers and places are rough hand-drawn approximations, also mock.

Run:  python3 -I apps/field-to-faucet/web/mock/_make_mock.py   (deterministic, seed 20261114)
"""
import datetime as dt
import json
import math
import os

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
RNG = np.random.default_rng(20261114)
NOTE = "MOCK DATA for UI development. Every value is synthetic and must not be cited."


def write(name, obj):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    print(f"{name:22s} {os.path.getsize(path)/1024:8.1f} KB")


def r(v, nd=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), nd)


def smooth(lon, lat, k=0):
    """Smooth pseudo-random spatial field in 0..1."""
    a = math.sin(lon * 3.1 + 1.7 * k) + math.sin(lat * 4.3 - 0.9 * k) + 0.6 * math.sin((lon + lat) * 7.7 + k)
    return (a + 2.6) / 5.2


# ---------------------------------------------------------------- HUC-12 scores (real outlines)
real_huc = json.load(open(os.path.join(DATA, "huc12.geojson")))
feats = real_huc["features"]
geoms = {f["properties"]["huc12"]: shape(f["geometry"]) for f in feats}

# focus area: ~9 contiguous Raccoon HUC-12s around Jefferson / Scranton (inside HLS tile 15TUG)
target = Point(-94.55, 42.05)
racc = [f["properties"]["huc12"] for f in feats if f["properties"]["basin"] == "raccoon"]
seed = min(racc, key=lambda h: geoms[h].centroid.distance(target))
focus = [seed]
while len(focus) < 9:
    cand = [h for h in racc if h not in focus and any(geoms[h].touches(geoms[g]) or geoms[h].intersects(geoms[g]) for g in focus)]
    if not cand:
        break
    focus.append(min(cand, key=lambda h: geoms[h].centroid.distance(target)))

def round_coords(c, nd=4):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [round_coords(x, nd) for x in c]

out_feats = []
for f in feats:
    p = dict(f["properties"])
    c = geoms[p["huc12"]].centroid
    row = 0.45 + 0.45 * smooth(c.x, c.y, 1)
    pd_ = 0.15 + 0.5 * smooth(c.x, c.y, 2)
    bare = 25 + 70 * smooth(c.x, c.y, 3) * row
    leak = row * (0.4 + pd_) * (bare / 60) * (0.85 + 0.3 * RNG.random())
    p.update(row_crop_share=r(row), poorly_drained_share=r(pd_), bare_days_wet=round(bare), leak_index=r(leak),
             in_focus=p["huc12"] in focus)
    out_feats.append({"type": "Feature", "properties": p,
                      "geometry": {"type": f["geometry"]["type"], "coordinates": round_coords(f["geometry"]["coordinates"])}})
for basin in ("raccoon", "desmoines"):
    fs = [f for f in out_feats if f["properties"]["basin"] == basin]
    tot = sum(f["properties"]["leak_index"] * f["properties"]["area_km2"] for f in fs)
    for f in fs:
        f["properties"]["share_of_basin_leak"] = r(f["properties"]["leak_index"] * f["properties"]["area_km2"] / tot, 4)
    for i, f in enumerate(sorted(fs, key=lambda f: -f["properties"]["share_of_basin_leak"])):
        f["properties"]["rank"] = i + 1
write("huc12.geojson", {"type": "FeatureCollection", "mock": True, "note": NOTE + " Outlines are real (WBD); scores are synthetic.", "features": out_feats})

# ---------------------------------------------------------------- fields (400 m squares in EPSG:5070)
to5070 = Transformer.from_crs(4326, 5070, always_xy=True)
to4326 = Transformer.from_crs(5070, 4326, always_xy=True)
focus_union = unary_union([geoms[h] for h in focus])
from shapely.ops import transform as shp_transform
fu5070 = shp_transform(lambda x, y, z=None: to5070.transform(x, y), focus_union)
minx, miny, maxx, maxy = fu5070.bounds
S = 400.0
x0, y0 = math.floor(minx / S) * S, math.floor(miny / S) * S
fields, details = [], {}
months = list(range(1, 13))
rain_norm = np.array([22, 25, 55, 90, 120, 125, 100, 105, 80, 65, 50, 33], float)
storm_norm = np.array([0, 0.2, 0.8, 1.6, 2.6, 2.8, 1.8, 1.7, 1.1, 0.8, 0.4, 0.1])
wet_norm = np.array([0.66, 0.67, 0.72, 0.76, 0.78, 0.74, 0.64, 0.58, 0.56, 0.6, 0.64, 0.66])
drain_names = ["Poorly drained", "Somewhat poorly drained", "Moderately well drained", "Well drained"]
fid = 10000
huc_by_pt = [(h, shp_transform(lambda x, y, z=None: to5070.transform(x, y), geoms[h])) for h in focus]
today = dt.date(2026, 11, 10)
y = y0
while y < maxy:
    x = x0
    while x < maxx:
        cx, cy = x + S / 2, y + S / 2
        pt = Point(cx, cy)
        if fu5070.contains(pt) and RNG.random() < 0.32:
            huc = next((h for h, g in huc_by_pt if g.contains(pt)), focus[0])
            ring = [to4326.transform(*xy) for xy in [(x, y), (x + S, y), (x + S, y + S), (x, y + S), (x, y)]]
            lon, lat = to4326.transform(cx, cy)
            fid += 1
            f_id = f"F{fid:05d}"
            start_c = RNG.random() < 0.5
            seq = "".join(("C" if (i % 2 == 0) == start_c else "S") for i in range(10))
            if RNG.random() < 0.12:
                seq = "CCCSCCSCCC"[: 10]
            if RNG.random() < 0.05:
                seq = seq[:6] + "OHCS"
            dclass = int(np.clip(RNG.normal(1.2 - 1.2 * smooth(lon, lat, 2) + 1.0, 0.9), 0, 3))
            slope = float(np.clip(RNG.gamma(2.0, 1.2) + 2 * smooth(lon, lat, 5), 0.2, 14))
            winter_cover = RNG.random() < 0.08
            spring_bare = 0.75 + 0.2 * RNG.random() - (0.5 if winter_cover else 0)
            bare = np.array([0.95, 0.95, 0.93, spring_bare + 0.1, spring_bare, 0.55, 0.08, 0.04, 0.1, 0.45, 0.85, 0.93])
            bare = np.clip(bare + RNG.normal(0, 0.03, 12), 0, 1)
            rain = rain_norm * (0.85 + 0.3 * smooth(lon, lat, 7)) + RNG.normal(0, 4, 12)
            storms = np.clip(storm_norm * (0.8 + 0.4 * RNG.random()), 0, None)
            wet = np.clip(wet_norm + (0.06 if dclass <= 1 else -0.02) + RNG.normal(0, 0.01, 12), 0, 1)
            risk = bare * (rain / rain.max()) * wet * (1.3 if dclass <= 1 else 0.9)
            risk = risk / max(risk.max(), 1e-6)
            leak = float(np.clip((1.4 - 0.35 * dclass) * spring_bare * (0.8 + 0.4 * RNG.random()) + 0.03 * slope, 0, 2))
            lb50 = 14 + 22 * leak
            props = {"field_id": f_id, "huc12": huc, "seq": seq, "leak_index": r(leak), "drainage": drain_names[dclass], "slope_pct": r(slope, 2)}
            fields.append({"type": "Feature", "properties": props,
                           "geometry": {"type": "Polygon", "coordinates": [[[round(a, 5), round(b, 5)] for a, b in ring]]}})
            # recent NDVI: last ~12 months of HLS-like observations
            nd_dates, nd_vals = [], []
            d = today - dt.timedelta(days=365)
            while d <= today:
                if RNG.random() < 0.6:
                    doy = d.timetuple().tm_yday
                    v = 0.18 + 0.68 * math.exp(-((doy - 205) / 38) ** 2) + (0.25 * math.exp(-((doy - 120) / 20) ** 2) if winter_cover else 0)
                    nd_dates.append(d.isoformat())
                    nd_vals.append(r(v + RNG.normal(0, 0.04), 2))
                d += dt.timedelta(days=8)
            kept1 = lb50 * 0.45
            kept2 = lb50 * 0.38
            kept3 = lb50 * 0.12
            def rng3(m, lo, hi):
                return {"p10": r(m * lo, 1), "p50": r(m, 1), "p90": r(m * hi, 1)}
            details[f_id] = {
                "seq": seq, "crop_2025": {"C": "corn", "S": "soybean", "O": "oats", "H": "hay"}.get(seq[-1], "other"),
                "drainage": drain_names[dclass], "slope_pct": r(slope, 2),
                "leak": {"lbN_ac_yr": rng3(lb50, 0.62, 1.45)},
                "calendar": {"months": months, "bare_frac": [r(v, 2) for v in bare], "rain_mm": [r(v, 0) for v in rain],
                             "storm_days": [r(v, 1) for v in storms], "wetness": [r(v, 2) for v in wet], "leak_risk": [r(v, 2) for v in risk]},
                "ndvi_recent": {"dates": nd_dates, "ndvi": nd_vals},
                "cover_years": {str(yr): bool(winter_cover and RNG.random() < 0.8) for yr in range(2016, 2026)},
                "strategies": {
                    "S0": {"lbN_kept_ac": rng3(0, 1, 1), "fert_value_usd_ac": rng3(0, 1, 1)},
                    "S1": {"lbN_kept_ac": rng3(kept1, 0.45, 1.5), "fert_value_usd_ac": rng3(kept1 * 0.62, 0.45, 1.5)},
                    "S2": {"lbN_kept_ac": rng3(kept2, 0.4, 1.6), "fert_value_usd_ac": rng3(kept2 * 0.62, 0.4, 1.6)},
                    "S3": {"lbN_kept_ac": rng3(kept3, 0.3, 1.8), "fert_value_usd_ac": rng3(kept3 * 0.62, 0.3, 1.8)},
                },
            }
        x += S
    y += S
li = np.array([f["properties"]["leak_index"] for f in fields])
order = li.argsort().argsort()
for f, o in zip(fields, order):
    f["properties"]["leak_pctile"] = round(100 * o / max(len(fields) - 1, 1))
write("fields.geojson", {"type": "FeatureCollection", "mock": True, "note": NOTE, "features": fields})
# split form (contract allows field_detail/<huc12>.json) so the app loads one HUC-12 at a time
os.makedirs(os.path.join(HERE, "field_detail"), exist_ok=True)
for old in os.listdir(os.path.join(HERE, "field_detail")):
    os.remove(os.path.join(HERE, "field_detail", old))
for h in focus:
    part = {k: v for k, v in details.items() if next(f for f in fields if f["properties"]["field_id"] == k)["properties"]["huc12"] == h}
    if part:
        write(f"field_detail/{h}.json", {"mock": True, "note": NOTE, **part})

# ---------------------------------------------------------------- river series
start, end = dt.date(2016, 1, 1), dt.date(2026, 11, 10)
dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
year_wet = {2016: 1.0, 2017: 0.9, 2018: 1.05, 2019: 1.15, 2020: 0.8, 2021: 0.55, 2022: 0.7, 2023: 0.75, 2024: 1.0, 2025: 1.3, 2026: 1.2}

def series(site_scale, lag):
    obs, p10, p50, p90, q = [], [], [], [], []
    noise = 0.0
    for d in dates:
        doy = d.timetuple().tm_yday
        w = year_wet[d.year]
        base = 3.0 + site_scale * w * (7.5 * math.exp(-((doy - 150 - lag) / 42) ** 2) + 2.2 * math.exp(-((doy - 330) / 40) ** 2))
        noise = 0.93 * noise + RNG.normal(0, 0.35)
        o = max(0.3, base + noise)
        m = max(0.3, base + 0.4 * noise + RNG.normal(0, 0.25))
        gap = (d.month in (1, 2) and RNG.random() < 0.9) or (d.year == 2019 and d.month == 8) or (RNG.random() < 0.01)
        obs.append(None if gap else r(o, 2))
        p50.append(r(m, 2)); p10.append(r(m * 0.74, 2)); p90.append(r(m * 1.3, 2))
        q.append(r(800 + 6000 * w * math.exp(-((doy - 140) / 50) ** 2) * (1 + 0.3 * noise), 0))
    return obs, q, p10, p50, p90

rs = {"mock": True, "note": NOTE, "mcl": 10,
      "split": {"train": ["2016-01-01", "2022-12-31"], "test": ["2023-01-01", "2025-12-31"], "live": ["2026-01-01", end.isoformat()]},
      "sites": {}}
for site, name, sc, lag in (("05484500", "Raccoon River at Van Meter, IA", 1.0, 0), ("05482000", "Des Moines River at 2nd Ave, Des Moines, IA", 0.8, 12)):
    o, q, a, b, c = series(sc, lag)
    rs["sites"][site] = {"name": name, "dates": [d.isoformat() for d in dates], "obs": o, "q_cfs": q, "p10": a, "p50": b, "p90": c}
write("river_series.json", rs)

# ---------------------------------------------------------------- scenarios
rac = rs["sites"]["05484500"]
levels_x = list(range(0, 55, 5))
by_year = {}
replay = None
for yr in (2023, 2024, 2025):
    idx = [i for i, d in enumerate(dates) if d.year == yr]
    obs = [rac["obs"][i] for i in idx]
    base = [rac["p50"][i] for i in idx]
    days_obs = sum(1 for v in obs if v is not None and v > 10)
    plant_obs = sum(1 for v in obs if v is not None and v > 9.5)
    ban_obs = 12 if yr == 2025 else 0
    lv, by_level = [], {}
    for x in levels_x:
        eff = 0.0072 * x  # synthetic: 0.36 cut at 50 %
        sim = []
        for i, v in zip(idx, base):
            doy = dates[i].timetuple().tm_yday
            season = 1.0 if 60 < doy < 200 else 0.4
            sim.append(r(max(0.3, 3.0 + (v - 3.0) * (1 - eff * season)), 2))
        by_level[str(x)] = sim
        d_sim = sum(1 for v in sim if v > 10)
        k = days_obs / max(sum(1 for v in base if v > 10), 1)
        d50 = round(d_sim * k)
        p50 = round(sum(1 for v in sim if v > 9.5) * k * plant_obs / max(days_obs, 1))
        def rr(v, lo=0.72, hi=1.25):
            return {"p50": round(v), "lo": round(v * lo if x else v), "hi": round(v * hi if x else v)}
        lv.append({"x": x, "days_over10": rr(d50), "plant_days": rr(p50), "cost_usd": rr(p50 * 13000, 0.6, 1.4),
                   "ban_days": rr(ban_obs * (1 - eff * 1.6) if ban_obs else 0), "load_tN": rr(9000 * (1 - eff * 0.7), 0.9, 1.1),
                   "lbN_kept": rr(9000 * eff * 0.7 * 2204.6, 0.5, 1.5)})
    by_year[str(yr)] = {"site": "05484500", "observed": {"days_over10": days_obs, "plant_days": plant_obs, "ban_days": ban_obs}, "levels": lv}
    if yr == 2025:
        replay = {"year": 2025, "site": "05484500", "dates": [dates[i].isoformat() for i in idx], "obs": obs, "base_p50": base, "by_level": by_level}
write("scenarios.json", {
    "mock": True, "note": NOTE, "adoption_levels": levels_x,
    "method": "MOCK: synthetic scaling of the modelled spring peak. The real scenario engine changes each field's living-cover pattern and propagates it through the learned watershed sensitivity, blended with trial priors.",
    "priors": [{"name": "MOCK cereal rye N-loss cut", "effect": -0.4, "range": [-0.57, -0.22], "source": "MOCK placeholder"}],
    "by_year": by_year, "replay": replay,
    "thresholds": {"plant_on_mgL": 9.5, "ban_mgL": 12, "cost_per_plant_day": {"lo": 10000, "hi": 16000}, "source": "MOCK placeholder"}})

# ---------------------------------------------------------------- outlook
last_i = max(i for i, v in enumerate(rac["obs"]) if v is not None)
lv = rac["obs"][last_i]
od = [today + dt.timedelta(days=i + 1) for i in range(14)]
p50 = [r(lv + 0.12 * i + 0.4 * math.sin(i / 3), 2) for i in range(14)]
p10 = [r(v - 0.3 - 0.18 * i, 2) for i, v in enumerate(p50)]
p90 = [r(v + 0.4 + 0.3 * i, 2) for i, v in enumerate(p50)]
prob = [r(min(0.95, max(0.01, (h - 10) / max(h - l, 0.1) * 0.9 + 0.05)), 2) for l, h in zip(p10, p90)]
write("outlook.json", {"mock": True, "note": NOTE, "issued": today.isoformat(), "site": "05484500",
                       "last_obs": {"date": dates[last_i].isoformat(), "value": lv}, "dates": [d.isoformat() for d in od],
                       "p10": p10, "p50": p50, "p90": p90, "prob_over10": prob,
                       "drivers": {"rain_7d_mm": 31, "rain_7d_pctile": 78, "gwetroot": 0.71, "gwetroot_pctile": 82, "bare_share": 0.86, "bare_share_pctile": 64},
                       "text": "MOCK: Wetter-than-usual soil and a rainy week over mostly bare fields push nitrate up over the next two weeks."})

# ---------------------------------------------------------------- strategies
NRCS = "https://www.nrcs.usda.gov/resources/guides-and-instructions/conservation-practice-standards"
write("strategies.json", {"mock": True, "note": NOTE, "disclaimer": "MOCK: Decision support, not a replacement for your agronomist.", "strategies": [
    {"id": "S0", "name": "Current corn-soybean (no cover)", "short": "Keep today's rotation",
     "why": "MOCK: the reference. Shows what the field does now so every other option is compared to it.",
     "evidence": [{"text": "MOCK evidence line", "source": "MOCK source", "url": "https://www.extension.iastate.edu/"}],
     "satellite_evidence": "MOCK: HLS shows the field bare from harvest to late May most years.",
     "n_loss_reduction": {"mean": 0, "lo": 0, "hi": 0, "source": "reference"},
     "yield_risk": {"level": "low", "text": "MOCK: no change."}, "soil_health": ["MOCK: no change"], "soil_score": 0,
     "gaps": ["MOCK gap"], "risks_local_review": ["MOCK risk"], "who_pays": [], "cost_usd_ac": {"lo": 0, "hi": 0, "source": "reference"}},
    {"id": "S1", "name": "Cereal rye before soybean", "short": "Plant rye after corn harvest, end it before soybeans",
     "why": "MOCK: living roots take up nitrate in the bare months when storms hit.",
     "evidence": [{"text": "MOCK trial summary", "source": "MOCK source", "url": "https://www.extension.iastate.edu/"}],
     "satellite_evidence": "MOCK: fields with rye green up 6 weeks earlier in HLS.",
     "n_loss_reduction": {"mean": 0.4, "lo": 0.22, "hi": 0.57, "source": "MOCK"},
     "yield_risk": {"level": "low", "text": "MOCK: little effect on soybean in most trials."},
     "soil_health": ["MOCK: less erosion", "MOCK: more organic matter"], "soil_score": 0.6,
     "gaps": ["MOCK gap"], "risks_local_review": ["MOCK risk"],
     "who_pays": [{"program": "EQIP 340 Cover Crop", "detail": "MOCK detail", "url": NRCS}, {"program": "Iowa cost share", "detail": "MOCK detail", "url": "https://iowaagriculture.gov/"}],
     "cost_usd_ac": {"lo": 25, "hi": 40, "source": "MOCK"}},
    {"id": "S2", "name": "Extended rotation (corn-soy-oats/clover)", "short": "Add a small grain + clover year",
     "why": "MOCK: a third crop keeps roots in the soil for more months.",
     "evidence": [{"text": "MOCK trial summary", "source": "MOCK source", "url": "https://www.extension.iastate.edu/"}],
     "satellite_evidence": "MOCK: extended-rotation fields stay green through fall in HLS.",
     "n_loss_reduction": {"mean": 0.35, "lo": 0.15, "hi": 0.55, "source": "MOCK"},
     "yield_risk": {"level": "medium", "text": "MOCK: one year of lower-value crop; corn after clover yields more."},
     "soil_health": ["MOCK: deeper roots", "MOCK: pest cycle broken", "MOCK: less erosion"], "soil_score": 0.9,
     "gaps": ["MOCK gap"], "risks_local_review": ["MOCK risk"],
     "who_pays": [{"program": "EQIP 328 Conservation Crop Rotation", "detail": "MOCK detail", "url": NRCS}],
     "cost_usd_ac": {"lo": 30, "hi": 80, "source": "MOCK"}},
    {"id": "S3", "name": "Split / in-season N", "short": "Apply nitrogen when the crop needs it",
     "why": "MOCK: less nitrate sits in the soil in spring.",
     "evidence": [{"text": "MOCK trial summary", "source": "MOCK source", "url": "https://www.extension.iastate.edu/"}],
     "satellite_evidence": "MOCK: no direct satellite signal; uses field leak timing.",
     "n_loss_reduction": {"mean": 0.1, "lo": 0.0, "hi": 0.2, "source": "MOCK"},
     "yield_risk": {"level": "low", "text": "MOCK: similar yield if timed well."},
     "soil_health": ["MOCK: small"], "soil_score": 0.1,
     "gaps": ["MOCK gap"], "risks_local_review": ["MOCK risk"],
     "who_pays": [{"program": "EQIP 590 Nutrient Management", "detail": "MOCK detail", "url": NRCS}],
     "cost_usd_ac": {"lo": 5, "hi": 15, "source": "MOCK"}},
]})

# ---------------------------------------------------------------- meta, validation, facts
write("meta.json", {"mock": True, "note": NOTE, "generated_at": "MOCK",
    "data_through": {"nwis": "MOCK", "power": "MOCK", "modis": "MOCK", "hls": "MOCK", "cdl": "MOCK"},
    "sources": [
        {"name": "MOCK HLS (Landsat + Sentinel-2)", "nasa": True, "role": "MOCK role", "url": "https://hls.gsfc.nasa.gov/"},
        {"name": "MOCK GPM IMERG", "nasa": True, "role": "MOCK role", "url": "https://gpm.nasa.gov/data/imerg"},
        {"name": "MOCK NASA POWER", "nasa": True, "role": "MOCK role", "url": "https://power.larc.nasa.gov/"},
        {"name": "MOCK USGS NWIS", "nasa": False, "role": "MOCK role", "url": "https://waterdata.usgs.gov/"},
    ],
    "caveats": ["MOCK caveat: this whole file is a placeholder."]})
def met(nse, kge, rmse, cov, csi):
    return {"NSE": nse, "KGE": kge, "RMSE": rmse, "MAE": r(rmse * 0.75, 2), "bias": r(rmse * 0.1, 2), "coverage80": cov, "hit_rate": r(csi + 0.15, 2), "false_alarm": r(0.6 - csi, 2), "CSI": csi}
vsites = {}
for s, nm in (("05484500", "Raccoon River at Van Meter"), ("05482000", "Des Moines River at 2nd Ave")):
    vsites[s] = {"name": nm, "by_split": {sp: {"gbm": met(0.71 if sp == "test" else 0.84, 0.74, 1.2, 0.79, 0.58),
                                                "climatology": met(0.31, 0.42, 2.4, None, 0.21),
                                                "persistence_7d": met(0.55, 0.6, 1.7, None, 0.44)} for sp in ("train", "test")}}
write("validation.json", {"mock": True, "note": NOTE, "splits": rs["split"], "sites": vsites,
                          "lines": ["MOCK: plain-language line about out-of-time skill."], "crisis_2025": {"text": "MOCK: 2025 crisis summary."}})
write("facts.json", {"mock": True, "note": NOTE, "facts": {
    "people_served": {"value": 600000, "unit": "people", "label": "MOCK people served", "source": "MOCK", "url": "https://www.iowapublicradio.org/", "verified": False},
    "plant_days_2025": {"value": 110, "unit": "days", "label": "MOCK removal-plant days 2025", "source": "MOCK", "url": "https://www.ciww.org/", "verified": False},
    "plant_cost_2025_usd": {"value": 2200000, "unit": "USD", "label": "MOCK removal cost 2025", "source": "MOCK", "url": "https://www.ciww.org/", "verified": False},
    "ban_days_2025": {"value": 12, "unit": "days", "label": "MOCK watering-ban days", "source": "MOCK", "url": "https://www.iowapublicradio.org/", "verified": False},
    "fert_price_usd_lb_N": {"value": 0.62, "unit": "USD/lb N", "label": "MOCK N price", "source": "MOCK", "url": "https://www.ams.usda.gov/", "verified": False},
}})

# rivers.geojson and places.json: real files exist in web/data (context module), so no mock is written.

# manifest: lets the app know which mock files exist without probing (no 404s in the console)
names = sorted(n for n in os.listdir(HERE) if n.endswith((".json", ".geojson")) and not n.startswith("_"))
write("_manifest.json", {"mock": True, "files": names, "field_detail_split": sorted(n[:-5] for n in os.listdir(os.path.join(HERE, "field_detail")))})
print("focus HUC-12s:", focus, "fields:", len(fields))
