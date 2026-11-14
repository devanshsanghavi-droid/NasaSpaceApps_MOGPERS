"""Regenerate every web/data/*.json from data/processed/ (re-runnable).

    cd apps/water-clock/model && python3 run_all.py

Steps: well states (weather-adjusted LLT Kalman + EB pooling) -> kriging to fields and grid -> Monte Carlo years-left
-> county / GMD / region clocks -> water balance (pumping vs decline) -> hindcast validation -> GRACE comparison ->
rotation engine -> scenario + climate files -> meta. Intermediate tables go to data/raw/model_cache/ (gitignored).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import (PROC, CACHE, WEB, COUNTIES, GMDS, THRESHOLDS, THR_DEFAULT, CAP, CLOCK_WINDOW, PRIORS,  # noqa: E402
                    write_json, weighted_quantile, county_area_acres, rnd)
import wells_state  # noqa: E402
import water_balance  # noqa: E402
import clock  # noqa: E402
import validation  # noqa: E402
import grace_compare  # noqa: E402
import rotation  # noqa: E402
from strategies_text import cards, WIMAS_URL, NASS_URL, ERS_URL  # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def rng3(est, lo, hi, nd=2):
    return {"est": rnd(est, nd), "lo": rnd(lo, nd), "hi": rnd(hi, nd)}


def main():
    A, M = wells_state.load_annual()
    log("annual levels", len(A), "wells", A.well_id.nunique())

    # 1. well states on the clock window --------------------------------------------------------------
    wells, Ct, hyper, coefs, W, cum = wells_state.run_state(A, CLOCK_WINDOW, last_min=2018)
    wells.to_parquet(CACHE / "well_states.parquet")
    log("LLT wells", len(wells), "hyper", {k: round(float(v), 4) for k, v in hyper.items()}, "weather", coefs)

    # 2. water balance + regime term -------------------------------------------------------------------
    aq_frac, _ = water_balance.aquifer_fraction()
    WB, panel, wb_sum, dh = water_balance.fit(A, aq_frac)
    WB.to_parquet(CACHE / "water_balance_county.parquet")
    regime = water_balance.regime_model(dh, coefs)
    log("water balance: Sy_app post", round(wb_sum["posterior"]["sy_app"], 3), "regime", regime["floor_ft_yr"], regime["k_rel"])

    # 3. spatial + Monte Carlo --------------------------------------------------------------------------
    F, G, sp_info, dec_k, wl_k, cur = clock.build(A, wells, regime)
    F.to_parquet(CACHE / "fields_full.parquet")
    G.to_parquet(CACHE / "grid_full.parquet")
    pub, sat09 = clock.published_check(A, G)
    log("fields", len(F), "grid", len(G), "published check", {k: pub[k] for k in ("mae_ft", "median_diff_ft", "r")})
    cty, gmd, reg = clock.aggregate(F, Ct, regime)
    # sensitivity: Wallace (90% of its WIMAS irrigated acres lie in the GMD1 polygon) moved from GMD4 to GMD1
    _, gmd_wal, _ = clock.aggregate(F, Ct, regime, gmd_override={"20199": "GMD1"})

    # 4. county tables ----------------------------------------------------------------------------------
    WC = pd.read_parquet(PROC / "wimas_county_year.parquet")
    pump_recent = WC[(WC.year >= 2016) & (WC.year <= 2025)].groupby("county_fips").irr_af_gw.mean()
    acol = "irr_acres_gw" if "irr_acres_gw" in WC else "irr_acres"
    wimas_acres = WC[(WC.year >= 2021) & (WC.year <= 2025)].groupby("county_fips")[acol].mean()
    # corn share of groundwater-irrigated acres: CDL 250 m mode at each active point, share of corn years 2020-2024,
    # weighted by the point's reported acres (pairs with WIMAS acres and AF/acre, per notes/pumping.md)
    CP = pd.read_parquet(PROC / "cdl_points.parquet", columns=["pdiv_id", "year", "cdl_mode_class_250m"])
    CP = CP[CP.year >= 2020]
    corn_frac = CP.groupby("pdiv_id").cdl_mode_class_250m.agg(lambda s: float((s == "corn").mean()))
    Fc = F.assign(cf=F.id.map(corn_frac).fillna(0.0), w=F.acres.fillna(F.acres.median()))
    corn_share_cdl = Fc.groupby("fips").apply(lambda g: float(np.average(g.cf, weights=g.w)))
    ctx = {c["fips"]: c for c in json.load(open(PROC / "county_context.json"))["counties"]}
    area = county_area_acres()
    WBi = WB.set_index("county_fips")
    Cti = Ct.set_index("county_fips")
    nwell = wells.groupby("county_fips").size()

    def sigma_reg(d):
        return math.sqrt(regime["floor_ft_yr"] ** 2 + (regime["k_rel"] * abs(d)) ** 2)

    # Observed decline averaged over the county's aquifer cells (same areal basis as the water-balance
    # pumping-attributable decline, which is pumping / (aquifer area x Sy_app)).
    Gaq = G[G.present & np.isfinite(G.sat)]
    d_aq_cty = Gaq.groupby("fips").decl.mean()

    counties_out, scen = [], {}
    Fv = F[np.isfinite(F.sat)]
    for f, (name, g) in COUNTIES.items():
        c = cty.get(f)
        cx = ctx.get(f, {})
        ca = cx.get("census_of_ag_2022", {}) or {}
        irr_ac = float(wimas_acres.get(f, np.nan))
        corn_share = float(corn_share_cdl.get(f, np.nan))
        corn_ac = irr_ac * corn_share if np.isfinite(corn_share) else None
        # decline used for the county clock / scenario
        d_est = c["decline_est"]
        sub = Fv[Fv.fips == f]
        flag = None
        if d_est <= 0.05:
            pos = sub[sub.decl > 0]
            if len(pos):
                d_est = float(np.average(pos.decl, weights=pos.acres.fillna(pos.acres.median())))
                flag = "county mean decline is near zero or rising; decline shown is the mean over its declining fields"
        se_c = float(Cti.loc[f, "se_post"]) if f in Cti.index else 0.3
        sd = math.sqrt(se_c ** 2 + sigma_reg(d_est) ** 2)
        decl = rng3(d_est, d_est - 1.2816 * sd, d_est + 1.2816 * sd, 3)
        yl = {t: {p: rnd(v, 1) for p, v in c["years_left"][t].items()} for t in c["years_left"]}
        nw = int(nwell.get(f, 0))
        mdist = c["median_dist_km"]
        quality = "good" if (nw >= 30 and mdist <= 3.0) else ("fair" if nw >= 12 else "thin")
        towns = [t for t in cx.get("main_towns", [])][:3]
        town_note = None
        if towns:
            town_note = ("Main towns: " + ", ".join(f"{t['name']} ({t['population_2025']:,})" for t in towns) +
                         ". Town public-supply wells are not linked to this clock (not verified).")
        pa = float(pump_recent.get(f, np.nan))
        # Pumping-attributable decline. The water balance gives it on an aquifer-area basis (dpump_aq); the clock's
        # decline is an acre-weighted mean over irrigated points (higher, local). Put both on one basis: the pumping
        # share of the aquifer-mean observed decline, capped at 1, applied to the point decline.
        rel_se = WBi.loc[f, "invsy_post_se"] / WBi.loc[f, "invsy_post"]
        dpump_aq = float(WBi.loc[f, "invsy_post"] * pa / WBi.loc[f, "A_aq_acres"])
        d_aq = float(d_aq_cty.get(f, np.nan))
        def share_of(x):
            return float(np.clip(x / d_aq, 0, 1)) if (np.isfinite(d_aq) and d_aq > 0) else 1.0
        share = share_of(dpump_aq)
        share_lo, share_hi = share_of(dpump_aq * (1 - 1.2816 * rel_se)), share_of(dpump_aq * (1 + 1.2816 * rel_se))
        dpump = share * max(d_est, 0.0)
        k_loc = dpump / dpump_aq if dpump_aq > 0 else 1.0     # aquifer-area -> irrigated-point scaling
        ftper_aq = float(WBi.loc[f, "invsy_post"] * irr_ac / WBi.loc[f, "A_aq_acres"]) if irr_ac else None
        ftper = ftper_aq * k_loc if ftper_aq is not None else None
        sat_avail, below = {}, {}
        for t in THRESHOLDS:
            y50 = yl[str(t)]["p50"]
            below[str(t)] = bool(y50 is not None and y50 <= 0)
            if decl["est"] > 0:
                if y50 >= CAP:
                    # capped clock: y50 x decline would understate the thickness; use the median saturated thickness
                    # above T (never less than CAP x decline, so X = 0 still reproduces 100)
                    sat_avail[str(t)] = rnd(max(CAP * decl["est"], c["sat_thick_ft"]["p50"] - t), 3)
                else:
                    sat_avail[str(t)] = rnd(y50 * decl["est"], 5)
            else:
                sat_avail[str(t)] = rnd(max(c["sat_thick_ft"]["p50"] - t, 0.0), 2)
        counties_out.append(dict(
            fips=f, name=name, gmd=g,
            sat_thick_ft={p: rnd(v, 0) for p, v in c["sat_thick_ft"].items()},
            decline_ft_yr=decl, years_left=yl,
            irrigated_acres=rnd(irr_ac, 0), irrigated_acres_census_2022=ca.get("irrigated_land_acres"),
            irrigated_corn_acres_census_2022=ca.get("corn_grain_irrigated_acres"),
            pumping_af_yr=rnd(pa, 0), corn_share_irrigated=rnd(corn_share, 3), irrigated_corn_acres=rnd(corn_ac, 0),
            n_wells=nw, n_fields=c["n_fields"], median_dist_to_well_km=rnd(mdist, 1), data_quality=quality,
            share_irrigated_acres_under_25y=rnd(c["share_acres_lt25y"], 3),
            decline_note=flag, town_note=town_note,
            population=cx.get("population_2025"), main_towns=[t["name"] for t in towns],
            crop_sales_per_resident_usd=(cx.get("derived") or {}).get("crop_sales_per_resident_usd"),
            ag_share_of_economy=cx.get("share_of_economy_from_irrigated_ag"),
            econ_note=("Share of the local economy from irrigated agriculture: no published county figure was reachable "
                       "(BEA blocked); crop sales per resident (Census of Agriculture 2022) shown instead."),
        ))
        scen[f] = dict(
            name=name, gmd=g, sat_avail_ft=sat_avail, decline_ft_yr=decl,
            decline_from_pumping_ft_yr=rnd(dpump, 3),
            decline_from_pumping_ft_yr_range=rng3(dpump, share_lo * d_est, share_hi * d_est, 3),
            pumping_share=rnd(share, 3), pumping_share_capped=bool(np.isfinite(d_aq) and d_aq > 0 and dpump_aq >= d_aq),
            decline_from_pumping_aquifer_mean_ft_yr=rnd(dpump_aq, 3), decline_aquifer_mean_ft_yr=rnd(d_aq, 3),
            irrigated_corn_acres=rnd(corn_ac, 0), irrigated_acres=rnd(irr_ac, 0), pumping_af_yr=rnd(pa, 0),
            sy=rnd(WBi.loc[f, "sy_post"], 3), ft_per_af_ac=rnd(ftper, 4), ft_per_af_ac_aquifer_mean=rnd(ftper_aq, 4),
            aquifer_area_acres=rnd(WBi.loc[f, "A_aq_acres"], 0),
            years_p50={t: yl[t]["p50"] for t in map(str, THRESHOLDS)},
            median_below_threshold=below,
            median_below_threshold_note={t: (f"The median irrigated acre is already below {t} ft of saturated thickness, so "
                                             f"this threshold cannot show a gain; see the 15 ft threshold or field view.")
                                         if below[t] else None for t in below},
            decline_flag=flag)

    se_gmd = Ct.groupby("gmd").se_gmd.first().to_dict()

    def quality_of(fl):
        """Plurality of irrigated acres: good if >= 50% of acres are in 'good' counties, fair if good+fair >= 50%."""
        tot = sum(x["irrigated_acres"] or 0 for x in fl) or 1.0
        sh = {q: sum(x["irrigated_acres"] or 0 for x in fl if x["data_quality"] == q) / tot for q in ("good", "fair", "thin")}
        return "good" if sh["good"] >= 0.5 else ("fair" if sh["good"] + sh["fair"] >= 0.5 else "thin")

    def agg_block(key, sub_c, res):
        fl = [x for x in counties_out if x["fips"] in sub_c]
        irr = sum(x["irrigated_acres"] or 0 for x in fl)
        corn = sum(x["irrigated_corn_acres"] or 0 for x in fl)
        pump = sum(x["pumping_af_yr"] or 0 for x in fl)
        d = res["decline_est"]
        # SE of the mean decline: EB GMD-level SE (wells_state.pool_slopes); region = acre-weighted GMD SEs combined
        if key in se_gmd:
            se = float(se_gmd[key])
        else:
            wg = {gn: sum(x["irrigated_acres"] or 0 for x in counties_out if x["gmd"] == gn) for gn in GMDS}
            se = math.sqrt(sum((wg[gn] * se_gmd[gn]) ** 2 for gn in GMDS)) / sum(wg.values())
        return dict(sat_thick_ft={p: rnd(v, 0) for p, v in res["sat_thick_ft"].items()},
                    decline_ft_yr=rng3(d, d - 1.2816 * sd, d + 1.2816 * sd),
                    years_left={t: {p: rnd(v, 1) for p, v in res["years_left"][t].items()} for t in res["years_left"]},
                    irrigated_acres=rnd(irr, 0), pumping_af_yr=rnd(pump, 0), corn_share_irrigated=rnd(corn / irr if irr else None, 3),
                    irrigated_corn_acres=rnd(corn, 0), n_wells=int(sum(x["n_wells"] for x in fl)), n_fields=res["n_fields"],
                    share_irrigated_acres_under_25y=rnd(res["share_acres_lt25y"], 3),
                    share_irrigated_acres_capped=rnd(res["share_acres_capped"], 3),
                    decline_se_ft_yr=rnd(se, 3), data_quality=quality_of(fl), town_note=None)
    gmds_out = []
    for gname in GMDS:
        sub_c = [f for f, (n, g) in COUNTIES.items() if g == gname]
        b = agg_block(gname, sub_c, gmd[gname])
        gmds_out.append(dict(fips=gname, gmd=gname, name=gname.replace("GMD", "GMD "), **b))
    region = dict(name="Western Kansas GMD 1, 3 and 4 (26 counties)", **agg_block("region", list(COUNTIES), reg),
                  method=("Acre-weighted median over the region's groundwater-irrigated points of diversion of each point's "
                          "p10 / p50 / p90 years left."))
    wal = {gn: {t: {p: rnd(v, 1) for p, v in gmd_wal[gn]["years_left"][t].items()} for t in gmd_wal[gn]["years_left"]}
           for gn in ("GMD1", "GMD4")}
    clocks = dict(threshold_default_ft=THR_DEFAULT, thresholds_ft=THRESHOLDS, counties=counties_out, gmds=gmds_out,
                  region=region,
                  sensitivity=dict(wallace_in_gmd1=dict(
                      note=("Wallace is kept in GMD4 (contract county list) although 90% of its WIMAS irrigated acres lie in "
                            "the GMD1 polygon. Years left for GMD1 and GMD4 if Wallace is moved to GMD1:"),
                      years_left=wal)),
                  method=("Per field: saturated thickness (kriged winter 2024-2026 water level minus aquifer base at wells) and "
                          "weather-normalised 2011-2026 decline rate (local-linear-trend Kalman filter, kriged), Monte Carlo "
                          f"({clock.MC_DRAWS} draws) over kriging + aquifer-base uncertainty and decadal decline variability. County value = "
                          "acre-weighted median of its irrigated points' p10/p50/p90. 100 = 100 or more years (rising or flat); "
                          "share_irrigated_acres_capped = share of acres whose p50 is at that cap. Saturated thickness is "
                          "kriged from wells with a reliable aquifer base (sat_flag 'ok')."),
                  generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    write_json(WEB / "county_clocks.json", clocks, nd=3)

    # counties.geojson
    geo = json.load(open(PROC / "counties.geojson"))
    byf = {x["fips"]: x for x in counties_out}
    for ft in geo["features"]:
        p = ft["properties"]
        c = byf.get(p["fips"])
        y = c["years_left"][str(THR_DEFAULT)] if c else {}
        p.update(years_p10=y.get("p10"), years_p50=y.get("p50"), years_p90=y.get("p90"))
    write_json(WEB / "counties.geojson", geo, nd=5)

    # fields.json (all groundwater irrigation points with use in 2021-2025; no subsample needed for size)
    cols = ["id", "lon", "lat", "fips", "acres", "crop", "af_yr", "sat_ft", "decl", "y10", "y50", "y90", "capped"]
    rows = []
    for r in F.itertuples():
        capped = (1 if r.y30_p50 >= CAP - 1e-9 else 0) if np.isfinite(r.y30_p50) else None
        rows.append([int(r.id), rnd(r.lon, 4), rnd(r.lat, 4), r.fips, rnd(r.acres, 0), r.crop, rnd(r.af_yr, 0),
                     rnd(r.sat, 0), rnd(r.decl, 2), rnd(r.y30_p10, 0), rnd(r.y30_p50, 0), rnd(r.y30_p90, 0), capped])
    write_json(WEB / "fields.json", dict(
        columns=cols, rows=rows, threshold_ft=THR_DEFAULT,
        note=("All WIMAS groundwater irrigation points of diversion that reported use > 0 in 2021-2025 (no subsample). "
              "acres/af_yr = mean reported 2021-2025; crop = most frequent single crop reported 2021-2025, else CDL 250 m "
              "mode (2020-2024). sat_ft/decl/years from the state model at the point; null sat = outside the mapped aquifer. "
              "capped = 1 when y50 is at the 100-year cap (100 means 100 or more years).")),
        nd=4)

    # grid.json
    Gp = G[G.present & np.isfinite(G.sat)]
    write_json(WEB / "grid.json", dict(
        cell_deg=0.02, columns=["lon", "lat", "sat_ft", "decl_ft_yr", "years_p50", "capped"], threshold_ft=THR_DEFAULT,
        note="years_p50 = 100 means 100 or more years; capped = 1 marks those cells.",
        rows=[[rnd(a, 3), rnd(b, 3), rnd(s, 0), rnd(d, 2), rnd(y, 0), int(y >= CAP - 1e-9)] for a, b, s, d, y in
              zip(Gp.lon, Gp.lat, Gp.sat, Gp.decl, Gp.y30_p50)]), nd=3)
    log("wrote clocks / fields / grid")

    # 5. validation -------------------------------------------------------------------------------------
    val = validation.run(A)
    json.dump(val, open(CACHE / "validation_full.json", "w"), default=float, indent=1)
    log("validation done")

    # 6. GRACE ----------------------------------------------------------------------------------------------
    gr, reg_dh = grace_compare.compare(dh, aq_frac, sy_app=wb_sum["posterior"]["sy_app"])
    json.dump(gr, open(CACHE / "grace_compare_full.json", "w"), default=float, indent=1)
    GR = pd.read_parquet(PROC / "grace_region.parquet").sort_values("month")
    gm = json.load(open(PROC / "grace_maps.json"))
    t_all = gr["trends"]["2003_2026"]
    t_fo = gr["trends"]["2018_2026"]
    gfz = t_all.get("gfz_tws_cm", {})
    trend_wells = dict(est=t_all["wells_sy_mid"]["slope_cm_yr"], lo=t_all["wells_sy_hi"]["slope_cm_yr"],
                       hi=t_all["wells_sy_lo"]["slope_cm_yr"])
    trend_grace = dict(est=gfz.get("slope_cm_yr"), lo=gfz.get("slope_cm_yr") - 1.2816 * gfz.get("se_cm_yr"),
                       hi=gfz.get("slope_cm_yr") + 1.2816 * gfz.get("se_cm_yr"))
    WCreg = WC[(WC.year >= 2016) & (WC.year <= 2025)].groupby("year").irr_af_gw.sum().mean()
    region_area_cm = sum(area.values())  # acres
    pump_cm = WCreg / region_area_cm * 30.48
    t_app = t_all.get("wells_sy_app", {}).get("slope_cm_yr", float("nan"))
    grace_ratio = trend_wells["est"] / trend_grace["est"]
    notes_g = (f"Wells: aquifer-area-weighted mean winter water-level change chained from county means, times specific yield "
               f"0.15 (range 0.10-0.20), over the {gr['aquifer_area_fraction']*100:.0f}% of the region underlain by the aquifer. "
               f"Annual correlation with GFZ GRACE/GRACE-FO total water storage r = {gr['correlation']['gfz_tws_cm']['r_annual']:.2f} "
               f"(year-to-year changes r = {gr['correlation']['gfz_tws_cm']['r_first_difference']:.2f}). Both show the same drought "
               f"drawdowns, but the well-based storage loss 2003-2026 ({trend_wells['est']:.1f} cm/yr) is about "
               f"{grace_ratio:.0f}x the GRACE trend ({trend_grace['est']:.1f} cm/yr). With the water-balance apparent specific "
               f"yield ({wb_sum['posterior']['sy_app']:.2f}) instead of 0.15 the well-based trend is {t_app:.1f} cm/yr, about "
               f"{t_app/trend_grace['est']:.0f}x GRACE. Reported gross pumping "
               f"(WIMAS 2016-2025, {WCreg/1e6:.2f} million AF/yr) equals {pump_cm:.1f} cm/yr over the region; net depletion is "
               f"smaller (return flow, recharge) but the same order as the well-based number. A likely (untested) reason for the gap is "
               f"GRACE's ~300 km footprint, which mixes this concentrated loss with a larger area that includes non-irrigated land "
               f"(signal leakage) as well as neighbouring areas that are also losing water, so leakage alone may not explain it. "
               f"GRACE is therefore used as an independent check of timing and sign, not as a volume constraint. "
               f"Since GRACE-FO (2018-2026) the gap narrows: wells {t_fo['wells_sy_mid']['slope_cm_yr']:.1f} vs GRACE "
               f"{t_fo.get('gfz_tws_cm', {}).get('slope_cm_yr', float('nan')):.1f} cm/yr.")
    years = gr["years"]
    grace_out = dict(
        series=dict(dates=[d.strftime("%Y-%m-%d") for d in pd.to_datetime(GR.month)], gws_pct=GR.gws_pct.round(2).tolist(),
                    tws_cm=GR.tws_cm.round(2).tolist() if "tws_cm" in GR else None,
                    g3p_gws_cm=GR.g3p_gws_cm.round(2).tolist() if "g3p_gws_cm" in GR else None,
                    sources=gm.get("sources")),
        maps=dict(cell_deg=gm["cell_deg"], bbox=gm["bbox"], dates=gm["dates"], gws_pct=gm["gws_pct"],
                  lats=gm["region"].get("lat"), tws_trend_cm_yr=gm.get("tws_trend_cm_yr"),
                  row_order="north_up"),
        wells_vs_grace=dict(
            well_storage_anom_series=dict(dates=[f"{y}-01-15" for y in years], cm=gr["well_storage_anom_cm"]["mid"]),
            well_storage_anom_cm_sy_range=dict(lo=gr["well_storage_anom_cm"]["lo"], hi=gr["well_storage_anom_cm"]["hi"]),
            correlation=gr["correlation"]["gfz_tws_cm"]["r_annual"],
            correlation_detail=gr["correlation"],
            trend_wells_cm_yr=trend_wells, trend_grace_cm_yr=trend_grace, trends=gr["trends"],
            trend_wells_cm_yr_at_sy_app=dict(est=t_app, sy_app=wb_sum["posterior"]["sy_app"]),
            pumping_reported_cm_yr=pump_cm, notes=notes_g))
    write_json(WEB / "grace.json", grace_out, nd=3)
    log("grace done")

    # 7. rotation engine -----------------------------------------------------------------------------------
    cw = rotation.crop_water()
    Y = rotation.yields()
    P, cost = rotation.prices_costs()
    per_county, comp = rotation.build(cw, Y, P, cost)
    sens = rotation.climate_sensitivity()
    modis = rotation.modis_check()
    sher = rotation.sheridan_check()
    cot = rotation.cotton_counties()
    corn_w = {f: (byf[f]["irrigated_corn_acres"] or 0) for f in COUNTIES}

    def wavg(vals, fips):
        w = np.array([corn_w[f] for f in fips], float)
        v = np.array(vals, float)
        m = np.isfinite(v) & (w > 0)
        return float(np.average(v[m], weights=w[m])) if m.any() else float("nan")

    reg_w = cw["corn"]["region"]
    V = dict(corn_in=float(reg_w["est"]), corn_lo=float(reg_w["lo"]), corn_hi=float(reg_w["hi"]),
             sorghum_in=float(cw["sorghum"]["region"]["est"]), wheat_in=float(cw["wheat"]["region"]["est"]),
             cotton_in=float(cw["cotton"]["region"]["est"]),
             cv_corn_irr=Y["corn"]["cv"].get("IRRIGATED", float("nan")), cv_corn_dry=Y["corn"]["cv"].get("NON-IRRIGATED", float("nan")),
             cv_wheat_dry=Y["wheat"]["cv"].get("NON-IRRIGATED-FALLOW", Y["wheat"]["cv"].get("NON-IRRIGATED", float("nan"))),
             wheat_fallow_ratio=float(np.median([v[0] for v in Y["wheat"]["ratios"].get("NON-IRRIGATED-FALLOW", {}).values()])),
             sorghum_dry_ratio=float(np.median([v[0] for v in Y["sorghum"]["ratios"].get("NON-IRRIGATED", {}).values()])),
             sher_pre=sher["sheridan_af_2008_2012"], sher_dur=sher["sheridan_af_2013_2017"], sher_chg=sher["sheridan_change_pct"],
             thomas_chg=sher["thomas_change_pct"], modis_corn_sorg=modis["corn_minus_sorghum_in"],
             n_cotton_counties=len(cot),
             sorghum_ers_irr_pct=float(json.load(open(PROC / "costs.json"))["crops"]["sorghum"]["Prairie Gateway"]["latest"]["irrigated_pct_of_acres"]),
             sorghum_ers_year=json.load(open(PROC / "costs.json"))["crops"]["sorghum"]["Prairie Gateway"]["latest_year"],
             cotton_acres_recent=float(WC[(WC.year >= 2021)].groupby("year").acres_cotton.sum().mean()))
    txt = cards(V)
    strategies = []
    all_f = list(COUNTIES)
    w0 = np.array([comp[f]["water"]["S0"] for f in all_f])
    for s in rotation.STRATS:
        sid = s["id"]
        fips_set = cot if sid == "S4" else all_f
        water = [comp[f]["water"][sid] for f in fips_set]
        inc_e = [comp[f]["income"][sid]["est"] for f in fips_set]
        inc_l = [comp[f]["income"][sid]["lo"] for f in fips_set]
        inc_h = [comp[f]["income"][sid]["hi"] for f in fips_set]
        west = wavg(water, fips_set)
        # water range: crop year-to-year range at region level
        if sid == "S0":
            wl, wh = reg_w["lo"], reg_w["hi"]
        elif sid == "S2":
            wl = wh = 0.0
        elif sid == "S3":
            wl, wh = cw["sorghum"]["region"]["lo"], cw["sorghum"]["region"]["hi"]
        elif sid == "S4":
            wl, wh = cw["cotton"]["region"]["lo"], cw["cotton"]["region"]["hi"]
        else:
            wl = (min(reg_w["lo"], rotation.LEMA_CORN_IN) + cw["wheat"]["region"]["lo"] + cw["sorghum"]["region"]["lo"]) / 3
            wh = (min(reg_w["hi"], rotation.LEMA_CORN_IN) + cw["wheat"]["region"]["hi"] + cw["sorghum"]["region"]["hi"]) / 3
        w0e = wavg([comp[f]["water"]["S0"] for f in fips_set], fips_set)
        pc = [(comp[f]["water"][sid] / comp[f]["water"]["S0"] - 1) * 100 for f in fips_set]
        pce = (west / w0e - 1) * 100
        strategies.append(dict(
            **s, **txt[sid],
            water_in_ac=rng3(west, wl, wh, 1),
            pumping_change_pct=rng3(pce, min(pc) if sid != "S0" else 0, max(pc) if sid != "S0" else 0, 1),
            income_usd_ac=rng3(wavg(inc_e, fips_set), wavg(inc_l, fips_set), wavg(inc_h, fips_set), 0),
            counties=fips_set if sid == "S4" else None))
    method = ("Water: WIMAS reported application depth on single-crop irrigated points, county median of 2011-2025 "
              "(GMD acre-weighted value where a county has too few acres); limited-irrigation corn capped at 11 in/acre "
              "(Sheridan-6 LEMA allocation). Income: return over USDA ERS Prairie Gateway operating costs, USD per acre, "
              "median (and 10th-90th percentile) over 2016-2025 of county yield x Kansas price - cost for the same year. "
              "Irrigated / dryland yields = county all-practice yield x the county's 2000-2018 NASS practice ratio (NASS stopped "
              "county irrigated yields after 2018). Region values weight counties by irrigated corn acres (WIMAS groundwater acres x CDL corn share). "
              "Fallow years count as zero income and zero cost. Not included: pumping energy, insurance, government payments, "
              "transition costs. This is decision support, not a replacement for your agronomist.")
    per_c = {f: {sid: dict(net_pumping_in_ac=rnd(v["net_pumping_in_ac"], 2), income_usd_ac=rnd(v["income_usd_ac"], 0))
                 for sid, v in per_county[f].items() if not (sid == "S4" and f not in cot)} for f in COUNTIES}
    write_json(WEB / "strategies.json", dict(strategies=strategies, per_county=per_c, method=method,
                                             crop_water_in_ac={k: v["region"] for k, v in cw.items()},
                                             modis_check_in=modis, sheridan_check=sher, sources=dict(
                                                 wimas=WIMAS_URL, nass=NASS_URL, ers=ERS_URL)), nd=3)
    log("strategies done")

    # 8. scenario.json ---------------------------------------------------------------------------------------
    formula = ("saved_af = X * irrigated_corn_acres * (net_S0 - net_Sk) / 12;  "
               "new_decline = decline_ft_yr - decline_from_pumping_ft_yr * saved_af / pumping_af_yr;  "
               "years = sat_avail_ft[T] / decline (100 if decline <= 0, capped at 100);  gain = years(new) - years(old). "
               "net_S0/net_Sk = strategies.per_county[fips][Sk].net_pumping_in_ac (in/acre/yr). "
               "decline_from_pumping_ft_yr = pumping_share * decline_ft_yr, where pumping_share = min(1, "
               "decline_from_pumping_aquifer_mean_ft_yr / decline_aquifer_mean_ft_yr): the water-balance pumping-attributable "
               "decline Q_recent / (A_aquifer * Sy_app) as a share of the observed decline averaged over the same aquifer "
               "area, applied to the irrigated-point decline (one basis for both). ft_per_af_ac is scaled the same way. "
               "sat_avail_ft[T] = years_p50[T] * decline_ft_yr, so X = 0 reproduces the county clock exactly; where the "
               "county clock is at the 100-year cap, sat_avail_ft[T] = max(100 * decline, sat_thick_p50 - T). Where "
               "median_below_threshold[T] is true the median acre is already below T and no gain can show at that T.")
    # verify that the client formula at X = 0 reproduces the baseline clock
    bad = []
    for f, s in scen.items():
        d = s["decline_ft_yr"]["est"]
        for t in map(str, THRESHOLDS):
            yb = CAP if d <= 0 else min(CAP, max(0.0, s["sat_avail_ft"][t]) / d)
            if abs(yb - min(CAP, s["years_p50"][t])) > 0.01 and not (d <= 0 and s["years_p50"][t] >= 99.9):
                bad.append((f, t, yb, s["years_p50"][t]))
    log("scenario zero-shift check mismatches:", bad)
    write_json(WEB / "scenario.json", dict(
        counties=scen, formula=formula, threshold_default_ft=THR_DEFAULT,
        water_balance=dict(method=water_balance.__doc__.strip(), summary=wb_sum,
                           note=("Response coefficient from the 26-county cross-section of long-term mean level change vs "
                                 "reported pumping depth (R2 shown), combined with the prior Sy 0.10-0.20. County time-series "
                                 "slopes were too confounded by weather to use (see notes/model.md).")),
        zero_shift_check="passed" if not bad else bad), nd=4)

    # 9. climate.json --------------------------------------------------------------------------------------
    cm = json.load(open(PROC / "cmip6_2045.json"))
    PW = pd.read_parquet(PROC / "power_county_annual.parquet")
    et0_base = PW[(PW.year >= 1995) & (PW.year <= 2014)].groupby("county_fips").et0_gs_in.mean()
    bE, bP = sens["all_crops"]["in_per_in_et0"], sens["all_crops"]["in_per_in_precip"]
    cE, cP = sens["corn"]["in_per_in_et0"], sens["corn"]["in_per_in_precip"]
    models = list(cm["models"].keys())
    reg_et0 = float(np.average([et0_base[f] for f in COUNTIES], weights=[byf[f]["irrigated_acres"] or 0 for f in COUNTIES]))
    # Clock shift is recomputed per field: each field's decline is raised by its county's ft_per_af_ac x extra
    # applied water, the same Monte Carlo is re-run with the same random draws (so the shift carries no MC noise), and
    # the shifted p50s are aggregated with the same acre-weighted median as the baseline clock. This keeps fields at
    # the 100-year cap with thick saturated sections at 100 instead of re-scaling a capped county number.
    Fm = F[np.isfinite(F.sat)].copy()
    Fm["w"] = Fm.acres.fillna(Fm.acres.median())
    ftp = Fm.fips.map({f: (scen[f]["ft_per_af_ac"] or 0.0) for f in COUNTIES}).values
    decs, dd_tab = {"base": F.decl.values}, {}
    for ssp in ("ssp245", "ssp585"):
        for m in models:
            mm = cm["models"][m][ssp]
            pct, dp = mm["et0_pm_gs_in_change_pct"], mm["pr_gs_in_change"]
            dIR = {f: bE * pct / 100 * et0_base[f] + bP * dp for f in COUNTIES}   # in/acre on irrigated acres
            dd_c = {f: (scen[f]["ft_per_af_ac"] or 0.0) * dIR[f] / 12 for f in COUNTIES}
            dd_tab[(ssp, m)] = dd_c
            decs[f"{ssp}|{m}"] = F.decl.values + F.fips.map(dd_c).fillna(0.0).values
    YC = clock.years_mc(F.sat.values, F.sat_sd.values, decs, F.decl_sd.values, thresholds=[30])
    okm = np.isfinite(F.sat.values)
    assert np.allclose(YC["base"][30][okm, 1], F.y30_p50.values[okm]), "climate MC does not reproduce the baseline draws"

    def agg_p50(y):
        yv = y[okm]
        out = {f: weighted_quantile(yv[(Fm.fips == f).values], Fm.w.values[(Fm.fips == f).values], .5) for f in COUNTIES}
        out["region"] = weighted_quantile(yv, Fm.w.values, .5)
        return out
    base_agg = agg_p50(YC["base"][30][:, 1])
    clim = {}
    for ssp in ("ssp245", "ssp585"):
        per_model = []
        for m in models:
            mm = cm["models"][m][ssp]
            pct, dp = mm["et0_pm_gs_in_change_pct"], mm["pr_gs_in_change"]
            new_agg = agg_p50(YC[f"{ssp}|{m}"][30][:, 1])
            cshift = {f: new_agg[f] - base_agg[f] for f in COUNTIES}
            wts = np.array([byf[f]["irrigated_acres"] or 0 for f in COUNTIES], float)
            dd_reg = float(np.average([dd_tab[(ssp, m)][f] for f in COUNTIES], weights=wts))
            per_model.append(dict(model=m, et0_pct=pct, dp=dp, extra_in_corn=cE * pct / 100 * reg_et0 + cP * dp,
                                  extra_in_all=bE * pct / 100 * reg_et0 + bP * dp,
                                  region_shift=new_agg["region"] - base_agg["region"], county=cshift, dd_reg=dd_reg))
        ens = lambda k: (float(np.mean([p[k] for p in per_model])), float(min(p[k] for p in per_model)),  # noqa: E731
                         float(max(p[k] for p in per_model)))
        e = ens("et0_pct"); pr = ens("dp"); xc = ens("extra_in_corn"); xa = ens("extra_in_all"); rs = ens("region_shift")
        cty_shift = {f: rng3(np.mean([p["county"][f] for p in per_model]), min(p["county"][f] for p in per_model),
                             max(p["county"][f] for p in per_model), 1) for f in COUNTIES}
        clim[ssp] = dict(et0_change_pct=rng3(*e, 1), gs_precip_change_in=rng3(*pr, 2), extra_pumping_in_ac=rng3(*xc, 2),
                         extra_pumping_in_ac_all_crops=rng3(*xa, 2),
                         clock_shift_years=dict(region=rng3(*rs, 1), county=cty_shift),
                         per_strategy_extra_in_ac={st["id"]: rnd(xc[0] * (st["water_in_ac"]["est"] / strategies[0]["water_in_ac"]["est"]), 2)
                                                   for st in strategies},
                         per_model=[{k: (rnd(v, 3) if not isinstance(v, (dict, str)) else v) for k, v in p.items() if k != "county"}
                                    for p in per_model])
    write_json(WEB / "climate.json", dict(
        scenarios=clim, baseline="1995-2014", future="2035-2055 (around 2045)", models=models,
        method=("Delta method: NEX-GDDP-CMIP6 Apr-Sep FAO-56 ET0 % change applied to each county's NASA POWER 1995-2014 Apr-Sep "
                "ET0; Apr-Sep precipitation change in inches. Irrigation response from a WIMAS county-year panel (1990-2025, "
                f"county fixed effects + trend): {bE:.2f} in of applied water per in of Apr-Sep ET0 and {bP:.3f} in per in of "
                f"Apr-Sep rain for all crops (corn: {cE:.2f} and {cP:.3f}). Extra pumping raises the decline by "
                "ft_per_af_ac x extra AF/acre at every irrigated point; the field Monte Carlo is re-run with the same random "
                "draws and the 30 ft clock re-aggregated (acre-weighted median), so county and region shifts are on the same "
                "basis as the baseline clock (counties at the 100-year cap stay there unless the extra decline brings them "
                "below it). Recharge changes are not modelled. Range = min-max over the 5 GCMs."),
        sensitivity=sens), nd=3)
    log("climate done")

    # 10. validation.json --------------------------------------------------------------------------------
    def mtab(d):
        return {k: {kk: rnd(vv, 3) for kk, vv in v.items()} for k, v in d.items() if isinstance(v, dict)}
    vout = {"summary": None, "train_end": 2014, "test_years": "2015-2026",
            "n_wells_test": val["fold_2014"]["temporal_holdout"]["n_wells"]}
    for fk, lab in (("fold_2014", "2014"), ("fold_2004", "2004")):
        fo = val[fk]
        vout[f"hindcast_{lab}_temporal_10yr_change_ft"] = mtab(fo["temporal_holdout"]["change_10yr"])
        vout[f"hindcast_{lab}_temporal_latest_level_ft"] = mtab(fo["temporal_holdout"]["level_latest"])
        vout[f"hindcast_{lab}_spatial_10yr_change_ft"] = mtab(fo["spatial_holdout"]["change_10yr"])
        vout[f"hindcast_{lab}_spatial_latest_level_ft"] = mtab(fo["spatial_holdout"]["level_latest"])
    f14 = val["fold_2014"]
    tc = f14["temporal_holdout"]["change_10yr"]
    sc = f14["spatial_holdout"]["change_10yr"]
    f04 = val["fold_2004"]
    tc4 = f04["temporal_holdout"]["change_10yr"]
    sc4 = f04["spatial_holdout"]["change_10yr"]

    def mrb(d):
        return f"MAE {d['mae']:.2f} / RMSE {d['rmse']:.2f} / bias {d['bias']:+.2f}"
    win_mae = tc["model"]["mae"] < tc["baseline_no_change"]["mae"]
    win_rmse = tc["model"]["rmse"] < tc["baseline_no_change"]["rmse"]
    verdict14 = ("beats no-change on both MAE and RMSE" if (win_mae and win_rmse) else
                 "beats no-change on MAE only, marginally, and loses on RMSE" if win_mae else
                 "beats no-change on RMSE only" if win_rmse else "does not beat no-change")
    sp_mae = sc["model"]["mae"] < sc["baseline_no_change"]["mae"]
    vout["summary"] = (
        f"10-yr change (ft), 2014 fold (trained on water levels through 2014, weather climatology through 2013; n = "
        f"{tc['model']['n']} wells): model {mrb(tc['model'])}; no-change {mrb(tc['baseline_no_change'])}; own-trend "
        f"{mrb(tc['baseline_own_trend'])}; county-trend {mrb(tc['baseline_county_trend'])}. The model {verdict14}: it "
        f"forecast a mean change of {tc['model']['bias'] + tc['observed_mean_change_ft']:+.1f} ft against "
        f"{tc['observed_mean_change_ft']:+.1f} ft observed, because declines slowed after 2014. Held-out wells (spatial, "
        f"re-fitted without them): model {mrb(sc['model'])} vs no-change {mrb(sc['baseline_no_change'])}"
        f"{'' if sp_mae else ' (model does not beat no-change)'}. 80% intervals covered {tc['model']['cov80']*100:.0f}% "
        f"(temporal) and {sc['model']['cov80']*100:.0f}% (spatial). The clear win is the 2004 fold, where declines sped up: "
        f"temporal model {mrb(tc4['model'])} vs no-change {mrb(tc4['baseline_no_change'])}; spatial model "
        f"{mrb(sc4['model'])} vs no-change {mrb(sc4['baseline_no_change'])}.")
    vout["saturated_thickness_vs_usgs_2009"] = {k: v for k, v in pub.items() if k != "alternative_wl_route"}
    vout["saturated_thickness_vs_usgs_2009"]["alternative_wl_route_mae_ft"] = pub["alternative_wl_route"]["mae_ft"]
    vout["water_balance"] = dict(
        cross_section_r2=wb_sum["cross_section"]["r2"], cross_section_sy_app=wb_sum["cross_section"]["sy_app"],
        posterior_sy_app=wb_sum["posterior"]["sy_app"], posterior_sy_app_80=wb_sum["posterior"]["sy_app_80"],
        within_county_timeseries_r2=wb_sum["fe_within"]["r2"], within_county_sy_app=wb_sum["fe_within"]["sy_app"],
        gmd4_timeseries_r2=wb_sum["gmd"]["GMD4"]["r2"], gmd3_timeseries_r2=wb_sum["gmd"]["GMD3"]["r2"],
        gmd1_timeseries_r2=wb_sum["gmd"]["GMD1"]["r2"])
    vout["grace_vs_wells"] = dict(correlation=gr["correlation"]["gfz_tws_cm"]["r_annual"],
                                  correlation_first_difference=gr["correlation"]["gfz_tws_cm"]["r_first_difference"],
                                  correlation_g3p_groundwater=gr["correlation"].get("g3p_gws_cm", {}).get("r_annual"),
                                  correlation_grace_da_percentile=gr["correlation"].get("grace_da_gws_pct", {}).get("r_annual"),
                                  trend_wells_cm_yr=trend_wells, trend_grace_cm_yr=trend_grace,
                                  trend_wells_cm_yr_at_sy_app=t_app,
                                  trend_wells_2018_2026_cm_yr=t_fo["wells_sy_mid"]["slope_cm_yr"],
                                  trend_grace_2018_2026_cm_yr=t_fo.get("gfz_tws_cm", {}).get("slope_cm_yr"),
                                  notes=notes_g)
    vout["model_settings"] = dict(clock_window=list(CLOCK_WINDOW), kalman_hyper_clock=hyper, weather_coefs_clock=coefs,
                                  regime_sd=dict(floor_ft_yr=regime["floor_ft_yr"], k_rel=regime["k_rel"]),
                                  kalman_hyper_fold_2014=f14["hyper"])
    write_json(WEB / "validation.json", vout, nd=4)

    # 11. meta.json ------------------------------------------------------------------------------------------
    meta = dict(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        region="Western Kansas Groundwater Management Districts 1, 3 and 4 (26 counties, High Plains / Ogallala aquifer)",
        data_sources=[
            dict(name="GRACE-DA groundwater percentiles (NASA GRACE/GRACE-FO data assimilation, UNL NDMC)", nasa=True,
                 role="Regional groundwater drought signal from space; consistency check with wells", status="partial",
                 url="https://nasagrace.unl.edu/", note="2025-10 missing (HTTP 404)"),
            dict(name="GRACE/GRACE-FO total water storage (GFZ GravIS RL06) and G3P groundwater", nasa=True,
                 role="Volumetric storage trend and correlation with wells", status="used",
                 url="https://isdc-data.gfz.de/grace/GravIS/"),
            dict(name="JPL / CSR GRACE mascons", nasa=True, role="Preferred volumetric GRACE product", status="blocked",
                 url="https://grace.jpl.nasa.gov/", note="No Earthdata login; CSR TLS failure"),
            dict(name="NASA POWER daily (MERRA-2/CERES) + FAO-56 ET0", nasa=True,
                 role="Weather adjustment of decline rates, irrigation-demand sensitivity, climate baseline", status="used",
                 url="https://power.larc.nasa.gov/"),
            dict(name="GPM IMERG daily (via NASA POWER)", nasa=True, role="Precipitation cross-check", status="partial",
                 url="https://power.larc.nasa.gov/", note="PC IMERG Zarr infeasible for annual totals"),
            dict(name="MODIS MOD16A3GF annual ET", nasa=True, role="Relative crop water use check (corn vs sorghum vs wheat)",
                 status="used", url="https://planetarycomputer.microsoft.com/dataset/modis-16A3GF-061"),
            dict(name="HLS (Harmonized Landsat Sentinel-2)", nasa=True,
                 role="Irrigated vs dryland detection test in dry spells (Haskell, Finney)", status="used",
                 url="https://planetarycomputer.microsoft.com/dataset/hls2-l30"),
            dict(name="NASA NEX-GDDP-CMIP6", nasa=True, role="2045 change in ET0 and rain -> clock shift", status="used",
                 url="https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html"),
            dict(name="OpenET (NASA-supported; not a NASA dataset)", nasa=False, role="Field-scale ET", status="blocked",
                 url="https://openetdata.org/", note="No API key"),
            dict(name="KGS WIZARD water levels", nasa=False, role="Winter water levels 1940-2026 (state model core)",
                 status="used", url="https://geohydro.kgs.ku.edu/geohydro/wizard/index.html"),
            dict(name="USGS Water Data API groundwater levels", nasa=False, role="Additional water levels", status="used",
                 url="https://api.waterdata.usgs.gov/ogcapi/v0/"),
            dict(name="USGS OFR 98-393 base of aquifer + KGS depth-to-bedrock picks", nasa=False,
                 role="Aquifer base for saturated thickness", status="used",
                 url="https://www.sciencebase.gov/catalog/item/631405f5d34e36012efa35b2"),
            dict(name="USGS SIR 2012-5177 saturated thickness 2009", nasa=False, role="Cross-check of saturated thickness",
                 status="used", url="https://www.sciencebase.gov/catalog/item/631405d0d34e36012efa33aa"),
            dict(name="KGS High Plains section database (bedrock per section)", nasa=False, role="Finer aquifer base",
                 status="blocked", url="http://hercules.kgs.ku.edu/geohydro/section_data/hp_step1.cfm"),
            dict(name="Kansas WIMAS water rights and water use", nasa=False,
                 role="Reported pumping per point of diversion; fields; crop water use", status="partial",
                 url=WIMAS_URL, note="Sherman 1998 missing"),
            dict(name="USDA NASS Cropland Data Layer", nasa=False, role="Crop at each point; county acreage", status="used",
                 url="https://www.nass.usda.gov/Research_and_Science/Cropland/"),
            dict(name="USDA NASS QuickStats bulk (yields, prices, Census of Agriculture 2022)", nasa=False,
                 role="Yields, prices, irrigated acres", status="partial", url=NASS_URL,
                 note="County irrigated yields end 2018 (corn), 2009 (sorghum)"),
            dict(name="USDA ERS Commodity Costs and Returns", nasa=False, role="Operating costs per acre", status="used",
                 url=ERS_URL),
            dict(name="KSU AgManager irrigated budgets", nasa=False, role="Irrigated vs dryland costs", status="blocked",
                 url="https://www.agmanager.info/"),
            dict(name="BEA county earnings", nasa=False, role="Share of economy from irrigated agriculture", status="blocked",
                 url="https://apps.bea.gov/"),
            dict(name="US Census population and county boundaries", nasa=False, role="Towns, population, maps",
                 status="used", url="https://www2.census.gov/"),
        ],
        caveats=[
            "Years left are a projection of the recent (2011-2026, weather-normalised) decline rate; they are not a forecast of "
            "what farmers or water managers will do. The hindcast shows declines can speed up or slow down by decade.",
            "Saturated thickness at a field is uncertain by roughly +/-20-30 ft because the aquifer base map is coarse "
            "(1:1,000,000, 200-ft contours plus KGS bedrock picks).",
            "0 years means the central estimate is already below the threshold; many wells still pump below 30 ft of saturated "
            "thickness, at reduced capacity.",
            "100 means 100 years or more (flat or rising water levels).",
            "County clocks summarise the groundwater-irrigated points of diversion (WIMAS) weighted by reported acres.",
            f"GRACE sees a ~300 km footprint; its 2003-2026 storage trend is about 1/{grace_ratio:.0f} of the well-based trend here "
            "(Sy 0.15; larger gap with the water-balance Sy), so it is used as a timing / sign check, not to scale the clock.",
            "Income uses ERS regional costs that do not separate irrigated from dryland farms and excludes pumping energy; "
            "irrigated yields after 2018 are estimated from earlier NASS ratios.",
            "Wallace County is kept in GMD4 as in the contract list, although 90% of its irrigated acres lie inside the GMD1 "
            "polygon (econ module check).",
            "This is decision support, not a replacement for your agronomist or for local water-right rules.",
        ])
    write_json(WEB / "meta.json", meta, nd=3, compact=False)

    # small model summary for notes
    summary = dict(region=region, gmds=gmds_out, counties=[{k: x[k] for k in ("fips", "name", "gmd", "sat_thick_ft",
                   "decline_ft_yr", "years_left", "n_wells", "data_quality")} for x in counties_out],
                   water_balance=wb_sum, regime=regime, spatial=sp_info, published_check=pub,
                   validation_summary=vout["summary"], scenario_check=bad)
    json.dump(summary, open(CACHE / "model_summary.json", "w"), default=float, indent=1)
    sizes = {p.name: p.stat().st_size for p in WEB.glob("*")}
    log("web/data sizes (KB):", {k: round(v / 1024) for k, v in sizes.items()}, "total MB", round(sum(sizes.values()) / 1e6, 2))


if __name__ == "__main__":
    main()
