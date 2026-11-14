"""Write SYNTHETIC mock files for UI development (web/mock/*.json).

Every number here is invented and deliberately round (multiples of 5, shares like 0.60) so it can never be mistaken for
a result. The app shows a red MOCK DATA banner whenever it loads any of these files. Schema mirrors CONTRACTS.md
"Web data contract". County ids come from web/data/counties.geojson (real Census geometry, owned by the geo module).

Run from apps/drought-bill/web:  /home/user/venv-db/bin/python mock/make_mock.py
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE.parent
random.seed(1)


def r5(x):
    return float(5 * round(x / 5))


def rng(est, lo_f=0.6, hi_f=1.5):
    return {"est": r5(est), "lo": r5(est * lo_f), "hi": r5(est * hi_f)}


def centroid(geom):
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def main():
    gj = json.loads((WEB / "data" / "counties.geojson").read_text())
    counties = {}
    region_tot = {"exp": 0, "tax": 0, "a22": 0, "a23": 0, "s245": 0, "s585": 0, "acres": 0}
    by_state = {}
    for f in gj["features"]:
        p = f["properties"]
        lon, lat = centroid(f["geometry"])
        w = min(1, max(0, (-lon - 89) / 14))  # 0 east .. 1 west: synthetic gradient only
        est = r5(10 + 40 * w)
        a22 = r5(est * (0.5 + 2.5 * w))
        acres = 100000.0
        now = round(1.2 - 0.6 * w, 1)
        divs = [0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]
        b22 = [r5(max(5, a22 * (1 - 0.25 * (d - now)))) for d in divs]
        c = {
            "name": p["name"], "state": p["state"], "insured_acres": acres, "liab_per_ac": 500.0,
            "subsidy_share": 0.60,
            "expected_bill": rng(est), "bill_1in5": rng(est * 2), "bill_1in10": rng(est * 4),
            "taxpayer_expected_bill": rng(est * 0.6),
            "actual": {"2012": r5(est * 3), "2022": a22, "2023": r5(est * 1.0)},
            "hindcast": {"2022": {"pred": r5(a22 * 0.8), "lo": r5(a22 * 0.5), "hi": r5(a22 * 1.2), "actual": a22},
                         "2023": {"pred": r5(est * 1.2), "lo": r5(est * 0.6), "hi": r5(est * 1.8), "actual": r5(est)}},
            "bill_2045": {"ssp245": rng(est * 1.2), "ssp585": rng(est * 1.4)},
            "diversity": {"now": now, "p90_region": 1.4, "n_crops_now": 2.0, "share_cont_corn": 0.20},
            "slider": {"div_values": divs, "bill_2022_style": b22,
                       "lo": [r5(b * 0.7) for b in b22], "hi": [r5(b * 1.3) for b in b22]},
            "irrigated_share": 0.10, "aws_mm": 200.0,
        }
        counties[p["fips"]] = c
        s = by_state.setdefault(p["state"], {"exp": 0, "tax": 0, "a22": 0, "a23": 0, "s245": 0, "s585": 0, "acres": 0})
        for t in (region_tot, s):
            t["exp"] += est * acres; t["tax"] += est * 0.6 * acres; t["a22"] += a22 * acres
            t["a23"] += est * acres; t["s245"] += est * 1.2 * acres; t["s585"] += est * 1.4 * acres; t["acres"] += acres

    (HERE / "county_bill.json").write_text(json.dumps(
        {"units": "USD per insured acre per year", "dollar_year": "2024", "mock": True, "counties": counties},
        separators=(",", ":")))

    def summ(t):
        return {
            "insured_acres": t["acres"],
            "expected_bill_usd": {"est": t["exp"], "lo": t["exp"] * 0.6, "hi": t["exp"] * 1.5},
            "taxpayer_share_usd": {"est": t["tax"], "lo": t["tax"] * 0.6, "hi": t["tax"] * 1.5},
            "actual_2022_usd": t["a22"], "actual_2023_usd": t["a23"],
            "bill_2045_usd": {"ssp245": {"est": t["s245"], "lo": t["s245"] * 0.6, "hi": t["s245"] * 1.5},
                              "ssp585": {"est": t["s585"], "lo": t["s585"] * 0.6, "hi": t["s585"] * 1.5}},
            "change_2045_pct": {"ssp245": {"est": 20.0, "lo": 0.0, "hi": 40.0},
                                "ssp585": {"est": 40.0, "lo": 10.0, "hi": 70.0}},
        }

    (HERE / "regional_summary.json").write_text(json.dumps({
        "units": "USD per year", "dollar_year": "2024", "mock": True,
        "region": dict(summ(region_tot), name="7-state Corn Belt and Plains"),
        "states": {k: summ(v) for k, v in sorted(by_state.items())},
    }, indent=1))

    (HERE / "hindcast.json").write_text(json.dumps({
        "mock": True, "train_years": [2001, 2020], "test_years": [2021, 2022, 2023, 2024],
        "metrics": {
            "model": {"mae": 10.0, "rmse": 15.0, "r2": 0.50, "spearman": 0.60, "total_bias_pct": -10.0},
            "baseline_mean": {"mae": 20.0, "rmse": 30.0, "r2": 0.00, "spearman": 0.30, "total_bias_pct": -50.0},
            "baseline_hazard_only": {"mae": 15.0, "rmse": 20.0, "r2": 0.30, "spearman": 0.50, "total_bias_pct": -20.0},
        },
        "by_year": {
            "2021": {"pred_total_usd": 1.0e9, "lo": 0.5e9, "hi": 1.5e9, "actual_total_usd": 1.0e9},
            "2022": {"pred_total_usd": 4.0e9, "lo": 3.0e9, "hi": 5.0e9, "actual_total_usd": 5.0e9},
            "2023": {"pred_total_usd": 3.0e9, "lo": 2.0e9, "hi": 4.0e9, "actual_total_usd": 3.5e9},
            "2024": {"pred_total_usd": 1.0e9, "lo": 0.5e9, "hi": 1.5e9, "actual_total_usd": 0.5e9},
        },
        "by_state": [{"state": s, "year": 2022, "pred_total_usd": v, "lo": v * 0.7, "hi": v * 1.3,
                      "actual_total_usd": v * 1.25}
                     for s, v in zip(["IA", "IL", "KS", "MN", "MO", "NE", "SD"],
                                     [0.5e9, 0.5e9, 1.0e9, 0.5e9, 0.5e9, 1.0e9, 0.5e9])],
    }, indent=1))

    strategies = [
        {"id": "current", "name": "Keep current rotation", "short": "Current",
         "description": "MOCK. What you grow now, as a baseline."},
        {"id": "cs_small_grain", "name": "Corn-soy-small grain", "short": "Add small grain",
         "description": "MOCK. Add wheat or oats every third year."},
        {"id": "cover_crop", "name": "Cereal rye cover crop", "short": "Cover crop",
         "description": "MOCK. Plant cereal rye after harvest."},
        {"id": "dt_swap", "name": "Drought-tolerant swap (sorghum)", "short": "Sorghum swap",
         "description": "MOCK. Replace some corn years with grain sorghum."},
    ]
    deltas = {"current": (0, 0, 0), "cs_small_grain": (-10, -20, -15), "cover_crop": (-5, -5, -10),
              "dt_swap": (-15, -30, -25)}
    grade = {"current": "strong", "cs_small_grain": "moderate", "cover_crop": "thin", "dt_swap": "moderate"}
    classes = {"corn-soy": 0, "continuous corn": 10, "3+ crop": -10, "with perennial": -15}
    texts = {
        "current": ("MOCK text. This is your baseline for comparison.", ["No change in equipment or markets"],
                    ["Field-level soil water not observed"], ["Drought exposure stays as it is"]),
        "cs_small_grain": ("MOCK text. A third crop breaks the corn-soy cycle.",
                           ["Spreads drought risk across seasons", "Breaks pest cycles"],
                           ["Few local yield trials"], ["Small-grain market access", "Extra equipment"]),
        "cover_crop": ("MOCK text. Living roots can improve infiltration.", ["Less erosion", "Better infiltration"],
                       ["Effect on drought losses is uncertain"], ["Can use spring soil water in dry years"]),
        "dt_swap": ("MOCK text. Sorghum tolerates heat and dry spells better.", ["Lower water demand in July"],
                    ["Insurance yield history for sorghum is short here"], ["Lower price per bushel", "Elevator access"]),
    }
    sc = {}
    fips_list = sorted(counties)
    pick = set(fips_list[::10]) | {"19149"}
    for fips in sorted(pick):
        base = counties[fips]["expected_bill"]["est"]
        sc[fips] = {}
        for cls, cadj in classes.items():
            cur = max(10.0, base + cadj)
            rows = []
            for s in strategies:
                dB, dT, dI = deltas[s["id"]]
                e = max(5.0, cur + dB)
                why, ben, gaps, risks = texts[s["id"]]
                rows.append({
                    "strategy_id": s["id"],
                    "expected_bill": rng(e), "bill_1in5": rng(e * 2), "bill_1in10": rng(e * 4),
                    "delta_bill": {"est": float(dB), "lo": float(dB - 10), "hi": float(dB + 5)},
                    "delta_bill_1in10": {"est": float(dT), "lo": float(dT - 20), "hi": float(dT + 10)},
                    "delta_income_per_ac": {"est": float(dI), "lo": float(dI - 20), "hi": float(dI + 20)},
                    "evidence": {"grade": grade[s["id"]], "sources": ["MOCK source"]},
                    "why": why, "benefits": ben, "gaps": gaps, "risks": risks,
                })
            sc[fips][cls] = rows
    (HERE / "strategies.json").write_text(json.dumps({"mock": True, "strategies": strategies, "counties": sc},
                                                     separators=(",", ":")))

    # focus fields: synthetic dots inside Plymouth County's bounding ring
    plym = next(f for f in gj["features"] if f["properties"]["fips"] == "19149")
    ring = plym["geometry"]["coordinates"][0] if plym["geometry"]["type"] == "Polygon" else plym["geometry"]["coordinates"][0][0]

    def inside(x, y):
        c = False
        for i in range(len(ring) - 1):
            (x1, y1), (x2, y2) = ring[i], ring[i + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c

    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    pats = {"corn-soy": "CS", "continuous corn": "C", "3+ crop": "CSW", "with perennial": "CSAA"}
    fields = []
    while len(fields) < 300:
        x = random.uniform(min(xs), max(xs)); y = random.uniform(min(ys), max(ys))
        if not inside(x, y):
            continue
        cls = random.choice(["corn-soy"] * 6 + ["continuous corn"] * 2 + ["3+ crop", "with perennial"])
        pat = pats[cls]; off = random.randrange(len(pat))
        seq = "".join(pat[(i + off) % len(pat)] for i in range(17))
        fields.append({"id": f"F{len(fields) + 1:03d}", "lon": round(x, 4), "lat": round(y, 4), "seq": seq,
                       "rotation_class": cls, "div5": {"corn-soy": 0.7, "continuous corn": 0.0, "3+ crop": 1.0,
                                                       "with perennial": 1.0}[cls],
                       "ncrop5": float(len(set(seq[-5:])))})
    (HERE / "focus_fields.json").write_text(json.dumps({"mock": True, "county": {"fips": "19149", "name": "Plymouth"},
                                                        "years": list(range(2008, 2025)), "fields": fields},
                                                       separators=(",", ":")))

    (HERE / "meta.json").write_text(json.dumps({
        "generated_at": "MOCK", "mock": True,
        "region": {"states": ["IA", "NE", "KS", "MO", "IL", "SD", "MN"]},
        "data_sources": [
            {"name": "NASA POWER (precipitation, temperature, root-zone soil wetness)", "nasa": True,
             "role": "Drought hazard", "url": "https://power.larc.nasa.gov/"},
            {"name": "MODIS MOD13Q1 NDVI", "nasa": True, "role": "Vegetation stress",
             "url": "https://planetarycomputer.microsoft.com/dataset/modis-13Q1-061"},
            {"name": "NASA NEX-GDDP-CMIP6", "nasa": True, "role": "2045 climate shift",
             "url": "https://planetarycomputer.microsoft.com/dataset/nasa-nex-gddp-cmip6"},
            {"name": "USDA RMA Cause of Loss and Summary of Business", "nasa": False, "role": "Insured losses",
             "url": "https://www.rma.usda.gov/"},
            {"name": "USDA NASS Cropland Data Layer", "nasa": False, "role": "Rotation diversity",
             "url": "https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php"},
        ],
        "caveats": ["MOCK caveat: these files are synthetic placeholders for layout only."],
    }, indent=1))
    print("mock files written:", sorted(p.name for p in HERE.glob("*.json")))


if __name__ == "__main__":
    main()
