"""Generate SHAPE-ONLY mock fixtures for UI development of the Water Clock web app.

EVERY VALUE HERE IS FAKE. Numbers are deliberately round (10, 20, 50, 100 ...) and county
shapes are schematic boxes, so nobody can mistake them for results. The app only reads these
files when the real file in web/data/ is missing, and then shows a red "MOCK DATA" banner.
Never copy anything from here into web/data/.

Run:  python3 make_mock.py   (from apps/water-clock/web/mock/)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Schematic layout: (fips, name, gmd, column, row). Boxes are NOT real county outlines.
COUNTIES = [
    ("20023", "Cheyenne", "GMD4", 0, 0), ("20153", "Rawlins", "GMD4", 1, 0), ("20039", "Decatur", "GMD4", 2, 0),
    ("20181", "Sherman", "GMD4", 0, 1), ("20193", "Thomas", "GMD4", 1, 1), ("20179", "Sheridan", "GMD4", 2, 1),
    ("20065", "Graham", "GMD4", 3, 1),
    ("20199", "Wallace", "GMD4", 0, 2), ("20109", "Logan", "GMD4", 1, 2), ("20063", "Gove", "GMD4", 2, 2),
    ("20071", "Greeley", "GMD1", 0, 3), ("20203", "Wichita", "GMD1", 1, 3), ("20171", "Scott", "GMD1", 2, 3),
    ("20101", "Lane", "GMD1", 3, 3),
    ("20075", "Hamilton", "GMD3", 0, 4), ("20093", "Kearny", "GMD3", 1, 4), ("20055", "Finney", "GMD3", 2, 4),
    ("20187", "Stanton", "GMD3", 0, 5), ("20067", "Grant", "GMD3", 1, 5), ("20081", "Haskell", "GMD3", 2, 5),
    ("20069", "Gray", "GMD3", 3, 5), ("20057", "Ford", "GMD3", 4, 5),
    ("20129", "Morton", "GMD3", 0, 6), ("20189", "Stevens", "GMD3", 1, 6), ("20175", "Seward", "GMD3", 2, 6),
    ("20119", "Meade", "GMD3", 3, 6),
]
YEARS = [(10, 20, 30), (20, 40, 60), (50, 100, 100), (5, 10, 20), (30, 50, 80)]
W, H, X0, Y0 = 0.5, 0.42, -102.0, 40.0


def box(c, r):
    x, y = X0 + c * W + 0.02, Y0 - r * H - 0.02
    return [[[x, y], [x + W - 0.04, y], [x + W - 0.04, y - H + 0.04], [x, y - H + 0.04], [x, y]]]


def yl(i, k=1.0):
    p10, p50, p90 = YEARS[i % len(YEARS)]
    return {"p10": min(100, round(p10 * k)), "p50": min(100, round(p50 * k)), "p90": min(100, round(p90 * k))}


def write(name, obj):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def main():
    feats, clocks, scen = [], [], {}
    for i, (fips, name, gmd, c, r) in enumerate(COUNTIES):
        y30 = yl(i)
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": box(c, r)},
                      "properties": {"fips": fips, "name": name + " (MOCK)", "gmd": gmd,
                                     "years_p10": y30["p10"], "years_p50": y30["p50"], "years_p90": y30["p90"]}})
        clocks.append({"fips": fips, "name": name + " (MOCK)", "gmd": gmd,
                       "sat_thick_ft": {"p10": 50, "p50": 100, "p90": 150},
                       "decline_ft_yr": {"est": 2, "lo": 1, "hi": 3},
                       "years_left": {"15": yl(i, 1.5), "30": y30, "50": yl(i, 0.5)},
                       "irrigated_acres": 100000, "pumping_af_yr": 100000, "corn_share_irrigated": 0.5,
                       "n_wells": 100, "data_quality": ["good", "fair", "thin"][i % 3],
                       "town_note": "MOCK town note - not real."})
        scen[fips] = {"sat_avail_ft": {"15": 85, "30": 70, "50": 50}, "decline_ft_yr": 2,
                      "decline_from_pumping_ft_yr": 1, "irrigated_corn_acres": 50000, "irrigated_acres": 100000,
                      "pumping_af_yr": 100000, "sy": 0.15, "ft_per_af_ac": None}
    write("mock_counties.geojson", {"type": "FeatureCollection", "features": feats})
    gmds = [{"fips": g, "name": g + " (MOCK)", "gmd": g, "sat_thick_ft": {"p10": 50, "p50": 100, "p90": 150},
             "decline_ft_yr": {"est": 2, "lo": 1, "hi": 3},
             "years_left": {"15": yl(k, 1.5), "30": yl(k), "50": yl(k, 0.5)},
             "irrigated_acres": 1000000, "pumping_af_yr": 1000000, "corn_share_irrigated": 0.5, "n_wells": 1000,
             "data_quality": "good", "town_note": None} for k, g in enumerate(["GMD1", "GMD3", "GMD4"])]
    write("mock_county_clocks.json", {"threshold_default_ft": 30, "thresholds_ft": [15, 30, 50],
                                      "counties": clocks, "gmds": gmds})

    rows, n = [], 0
    for i, (fips, name, gmd, c, r) in enumerate(COUNTIES):
        y = yl(i)
        for a in range(4):
            for b in range(3):
                n += 1
                lon = X0 + c * W + 0.08 + a * 0.1
                lat = Y0 - r * H - 0.08 - b * 0.1
                rows.append([f"MOCK{n}", round(lon, 2), round(lat, 2), fips, 100, "Corn (mock)", 100,
                             100, 2, y["p10"], y["p50"], y["p90"]])
    write("mock_fields.json", {"columns": ["id", "lon", "lat", "fips", "acres", "crop", "af_yr", "sat_ft",
                                           "decl", "y10", "y50", "y90"], "rows": rows})

    grid = []
    for i in range(10):
        for j in range(12):
            grid.append([round(-102.0 + i * 0.25 + 0.125, 3), round(37.0 + j * 0.25 + 0.125, 3), 100, 2,
                         [10, 20, 50, 100][(i + j) % 4]])
    write("mock_grid.json", {"cell_deg": 0.25, "rows": grid})

    def strat(sid, name, short, rot, irr, w, p, inc):
        return {"id": sid, "name": name + " (MOCK)", "short": short, "rotation": rot, "irrigation": irr,
                "why": "MOCK: placeholder reason.",
                "evidence": [{"text": "MOCK evidence line", "source": "Mock source", "url": "https://example.org/"}],
                "benefits": ["MOCK benefit"], "gaps": ["MOCK information gap"], "risks": ["MOCK risk for local review"],
                "soil_health": "MOCK soil health text", "water_in_ac": w, "pumping_change_pct": p,
                "income_usd_ac": inc, "yield_risk": "MOCK yield risk text", "applies_where": "MOCK: everywhere"}
    strategies = [
        strat("S0", "Continuous irrigated corn (current)", "Current", ["corn"], "full",
              {"est": 20, "lo": 10, "hi": 30}, {"est": 0, "lo": 0, "hi": 0}, {"est": 100, "lo": 0, "hi": 200}),
        strat("S1", "Corn-wheat-sorghum, limited irrigation", "Limited irrigation", ["corn", "wheat", "sorghum"],
              "limited", {"est": 10, "lo": 5, "hi": 15}, {"est": -50, "lo": -60, "hi": -40},
              {"est": 50, "lo": 0, "hi": 100}),
        strat("S2", "Dryland wheat-sorghum-fallow", "Dryland", ["wheat", "sorghum", "fallow"], "none",
              {"est": 0, "lo": 0, "hi": 0}, {"est": -100, "lo": -100, "hi": -100}, {"est": 0, "lo": -50, "hi": 50}),
        strat("S3", "Irrigated sorghum swap", "Sorghum swap", ["sorghum"], "limited",
              {"est": 10, "lo": 5, "hi": 15}, {"est": -50, "lo": -60, "hi": -40}, {"est": 50, "lo": 0, "hi": 100}),
    ]
    per_county = {c[0]: {"S0": {"net_pumping_in_ac": 20, "income_usd_ac": 100},
                         "S1": {"net_pumping_in_ac": 10, "income_usd_ac": 50},
                         "S2": {"net_pumping_in_ac": 0, "income_usd_ac": 0},
                         "S3": {"net_pumping_in_ac": 10, "income_usd_ac": 50}} for c in COUNTIES}
    write("mock_strategies.json", {"strategies": strategies, "per_county": per_county, "method": "MOCK method text."})
    write("mock_scenario.json", {"counties": scen, "formula": "MOCK formula text (see notes/frontend.md)."})

    dates, gws, tws = [], [], []
    for yr in range(2003, 2025):
        for m in (1, 4, 7, 10):
            k = len(dates)
            dates.append(f"{yr}-{m:02d}-01")
            gws.append(max(10, 90 - 10 * (k // 11)))
            tws.append(-1 * (k // 11) * 2)
    cells = [[[50, 50, 50, 50, 50], [40, 40, 40, 40, 40], [30, 30, 30, 30, 30], [20, 20, 20, 20, 20],
              [10, 10, 10, 10, 10], [10, 10, 10, 10, 10]]]
    write("mock_grace.json", {"series": {"dates": dates, "gws_pct": gws, "tws_cm": tws},
                              "maps": {"cell_deg": 0.5, "bbox": [-102.0, 37.0, -99.5, 40.0],
                                       "dates": ["2010-01-01", "2020-01-01"],
                                       "gws_pct": [cells[0], [[v - 10 if v > 10 else v for v in row] for row in cells[0]]]},
                              "wells_vs_grace": {"well_storage_anom_series": {"dates": [d for d in dates[::4]],
                                                                              "cm": [-2 * i for i in range(len(dates[::4]))]},
                                                 "correlation": 0.5, "trend_wells_cm_yr": -1.0,
                                                 "trend_grace_cm_yr": -1.0, "notes": "MOCK notes."}})
    write("mock_validation.json", {
        "hindcast": {
            "spatial_holdout": {"model": {"mae_decline_ft": 5, "rmse_decline_ft": 10, "coverage_80": 0.8},
                                "baseline_no_change": {"mae_decline_ft": 10, "rmse_decline_ft": 20, "coverage_80": None},
                                "baseline_county_trend": {"mae_decline_ft": 10, "rmse_decline_ft": 10, "coverage_80": None}},
            "temporal_holdout": {"model": {"mae_decline_ft": 5, "rmse_decline_ft": 10, "coverage_80": 0.8},
                                 "baseline_own_trend": {"mae_decline_ft": 10, "rmse_decline_ft": 10, "coverage_80": None}}},
        "n_wells_test": 100, "train_end": 2014, "test_years": "2015-2024",
        "grace_vs_wells": {"correlation": 0.5, "trend_wells_cm_yr": -1.0, "trend_grace_cm_yr": -1.0},
        "notes": "MOCK validation numbers."})
    write("mock_climate.json", {"scenarios": {
        "ssp245": {"et0_change_pct": {"est": 5, "lo": 0, "hi": 10}, "gs_precip_change_in": {"est": 0, "lo": -1, "hi": 1},
                   "extra_pumping_in_ac": {"est": 1, "lo": 0, "hi": 2}, "clock_shift_years": {"region": {"est": -1, "lo": -2, "hi": 0}}},
        "ssp585": {"et0_change_pct": {"est": 10, "lo": 5, "hi": 15}, "gs_precip_change_in": {"est": 0, "lo": -2, "hi": 1},
                   "extra_pumping_in_ac": {"est": 2, "lo": 1, "hi": 3}, "clock_shift_years": {"region": {"est": -2, "lo": -3, "hi": -1}}}},
        "baseline": "MOCK 1995-2014", "future": "MOCK 2035-2055", "models": ["MOCK-GCM-1", "MOCK-GCM-2", "MOCK-GCM-3"]})
    write("mock_meta.json", {"generated_at": "MOCK", "region": "MOCK - Western Kansas GMD 1, 3, 4",
                             "data_sources": [
                                 {"name": "Mock NASA source 1", "nasa": True, "role": "MOCK role", "url": "https://example.org/", "status": "used"},
                                 {"name": "Mock NASA source 2", "nasa": True, "role": "MOCK role", "url": "https://example.org/", "status": "partial"},
                                 {"name": "Mock partner source", "nasa": False, "role": "MOCK role", "url": "https://example.org/", "status": "blocked"}],
                             "caveats": ["MOCK DATA - shape-only fixture for UI development."]})


if __name__ == "__main__":
    main()
