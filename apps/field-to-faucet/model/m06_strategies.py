#!/usr/bin/env python3
"""m06_strategies.py: farmer strategy cards + per-field N kept (Field to Faucet).

Run after model/m05_fields.py:   python3 model/m06_strategies.py   (about 20 s, no network)

S0  current corn-soybean, no cover (reference)
S1  cereal rye before soybean (rye after corn harvest, ended before soybean planting; every other winter in corn-soy)
S2  extended rotation, 4 years: corn - soybean - oats with alfalfa seeded in - alfalfa (the INRS "4+ yr" practice;
    the ISU Marsden 4-yr system)
S3  perennial prairie on ~10% of the field (prairie strips / small land retirement)

N-loss reductions are practice efficiencies from the Iowa Nutrient Reduction Strategy (INRS), read from
docs/facts.json by id at run time. The more recent Mar 2024 Science Team update (`inrs_2024_update`) is the
primary prior where present; the older table value is shown as context. Each reduction is applied to the field's
own leak distribution (model/out/field_scores.parquet, quantile function from m05) by Monte Carlo:
   kept = leak x reduction x (share of the field and of the years the practice covers)
Fertilizer value = kept x N price (an UPPER bound: not all retained N is recovered by the next crop).

Outputs: model/out/strategies.json, model/out/field_detail.json (web contract shape).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
OUT = APP / "model" / "out"
FACTS = APP / "docs" / "facts.json"
PRIORS = APP.parents[1] / "shared" / "evidence" / "evidence_priors.json"
N_DRAWS = 4000
SEED = 20261115
DISCLAIMER = ("Decision support, not a replacement for your agronomist. Numbers are estimates from satellite data, "
              "weather, soils and Iowa field trials, calibrated to the rivers at Des Moines; check every option with "
              "your agronomist, NRCS or county office before changing anything.")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_facts():
    return {f["id"]: f for f in json.loads(FACTS.read_text())["facts"]}


def usable(f):
    return f is not None and f.get("verification") != "unverified"


def sd_from(f):
    """SD: structured field, else the first '(SD n)' in the claim."""
    if f.get("sd") is not None:
        return float(f["sd"])
    m = re.search(r"\(SD\s*(\d+(?:\.\d+)?)\)", f.get("claim", ""))
    return float(m.group(1)) if m else None


def efficiency(facts, fid, sd_fid=None, sub=None):
    """Return dict(mean, sd, source, url, older) in % with the 2024 update as primary when present."""
    f = facts[fid]
    old_mean = float(f["value"])
    old_sd = float(facts[sd_fid]["value"]) if sd_fid and sd_fid in facts else sd_from(f)
    upd = f.get("inrs_2024_update")
    if isinstance(upd, dict) and sub:
        upd = upd.get(sub)
    if isinstance(upd, dict) and upd.get("value") is not None:
        mean = float(upd["value"])
        sd = float(upd["sd"]) if upd.get("sd") is not None else old_sd
        sd_label = "2024 update" if upd.get("sd") is not None else "older table (2024 SD not given)"
        url = upd.get("url") or f["url"]
        return {"mean": mean, "sd": sd, "sd_label": sd_label, "edition": "INRS Science Team update, Mar 2024",
                "url": url, "older": {"mean": old_mean, "sd": old_sd, "edition": "INRS Feb 2025 Table 2 (unchanged since 2013)", "url": f["url"]},
                "verification": f["verification"]}
    return {"mean": old_mean, "sd": old_sd, "sd_label": "INRS table", "edition": "INRS Feb 2025 Table 2", "url": f["url"],
            "older": None, "verification": f["verification"]}


def priors_by_id():
    try:
        d = json.loads(PRIORS.read_text())
        return {p["prior_id"]: p for p in d["priors"]}
    except Exception:
        return {}


def q3(a):
    p = np.percentile(a, [10, 50, 90], axis=0)
    return p


def rnd(x, nd=1):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def main():
    t0 = time.time()
    facts = load_facts()
    pri = priors_by_id()
    fs = pd.read_parquet(OUT / "field_scores.parquet")
    chk = json.loads((OUT / "basin_index_check.json").read_text())
    rng = np.random.default_rng(SEED)

    # ---------------- priors from facts
    rye = efficiency(facts, "inrs_cover_rye_pct", sd_fid="inrs_cover_rye_sd")
    ext = efficiency(facts, "inrs_ext_rotation_pct")
    ext3 = efficiency(facts, "inrs_ext_rotation_pct", sub="three_year")
    crp = efficiency(facts, "inrs_crp_pct", sub="crp")   # 2024: "no new data" -> table value
    ps = facts.get("prairie_strips_nitrate")
    m = re.search(r"about\s*(\d+)%\s*of a cropped", (ps or {}).get("claim", ""))
    strip_frac = float(m.group(1)) / 100 if m else 0.10
    log("priors (%):", {"rye": (rye["mean"], rye["sd"]), "ext4": (ext["mean"], ext["sd"]), "ext3": (ext3["mean"], ext3["sd"]),
                        "crp": (crp["mean"], crp["sd"]), "strip_frac": strip_frac})

    fp = facts["fert_price_usd_lbN"]
    p_hi = float(fp["range"]["hi"]) if fp.get("range") else float(fp["value"])
    m = re.search(r"\$\s*(0\.\d+)\s*per lb", fp.get("notes", ""))
    p_isu = float(m.group(1)) if m else None
    p_lo = min(p_isu, float(fp["range"]["lo"])) if p_isu else float(fp["range"]["lo"])
    p_mid = float(fp["value"])
    price_src = (f"N price U[${p_lo:.2f}, ${p_hi:.2f}]/lb N: high = USDA AMS Iowa anhydrous ({fp['verification']}, {fp['url']}, "
                 f"${p_mid:.3f} central); low = {'ISU A1-88 2026 budget $%.2f/lb N' % p_isu if p_isu else 'AMS range low'}")

    # ---------------- Monte Carlo per field
    Q = np.stack(fs["leak_q200"].to_numpy())             # [field, 200] lb N/ac/yr quantile function
    nf, nq = Q.shape
    idx = rng.integers(0, nq, (N_DRAWS, nf))
    L = np.take_along_axis(Q.T, idx, axis=0)              # [draw, field] leak draws (independent per field)

    def red(e, n):
        return np.clip(rng.normal(e["mean"] / 100, e["sd"] / 100, n), 0, 1)

    r1, r2, r3 = red(rye, N_DRAWS), red(ext, N_DRAWS), red(crp, N_DRAWS)
    price = rng.uniform(p_lo, p_hi, N_DRAWS)
    freq_cs = fs["freq_soy_after_corn_2016_2025"].to_numpy(float)
    kept = {
        "S0": np.zeros_like(L),
        "S1": L * r1[:, None] * freq_cs[None, :],        # rye acts in soybean-after-corn crop years only
        "S2": L * r2[:, None],                            # whole rotation
        "S3": L * strip_frac * r3[:, None],               # converted ~10% assumed to leak at the field average
    }
    fert = {k: v * price[:, None] for k, v in kept.items()}
    kq = {k: q3(v) for k, v in kept.items()}
    fq = {k: q3(v) for k, v in fert.items()}
    kmean = {k: v.mean(axis=0) for k, v in kept.items()}      # long-run average per year (p50 = typical single year)
    fmean = {k: v.mean(axis=0) for k, v in fert.items()}
    lmean = L.mean(axis=0)

    def nlr(r):
        return {"lo": round(float(np.percentile(r, 10)), 3), "hi": round(float(np.percentile(r, 90)), 3)}

    # ---------------- satellite facts for card text (focus area, computed from data)
    bare = np.stack(fs["cal_bare_frac"].to_numpy())
    lshare = np.stack(fs["cal_leak_share"].to_numpy())
    storm = np.stack(fs["cal_storm_days"].to_numpy())
    octmay = [9, 10, 11, 0, 1, 2, 3, 4]
    aprjun = [3, 4, 5]
    bare_octmay = float(bare[:, octmay].mean())
    bare_aprjun = float(bare[:, aprjun].mean())
    leak_octmay = float(fs["frac_leak_oct_may"].mean())
    leak_aprjun = float(fs["frac_leak_apr_jun"].mean())
    storms_aprjun = float(storm[:, aprjun].sum(axis=1).mean() / storm.sum(axis=1).mean())
    cov = [json.loads(s) for s in fs["cover_years_json"]]
    cy = [(y, v) for d in cov for y, v in d.items() if 2021 <= int(y) <= 2026]
    cover_pct = 100 * np.mean([v for _, v in cy]) if cy else float("nan")
    any_cover = 100 * np.mean([any(v for y, v in d.items() if 2021 <= int(y) <= 2026) for d in cov])
    calib = chk.get("calibration", [])
    rac = [c for c in calib if c["basin"] == "raccoon"]
    rac_mean_lb = np.mean([c["lbN_ac_rowcrop_from_rowcrop"]["central"] for c in rac]) if rac else float("nan")

    def fact_ev(fid, text=None):
        f = facts.get(fid)
        if not usable(f):
            return None
        return {"text": text or f["claim"], "source": f"{f.get('publisher', '')} ({f['verification']})".strip(), "url": f["url"]}

    def prior_ev(pid, text=None):
        p = pri.get(pid)
        if not p:
            return None
        return {"text": text or p["summary"], "source": f"{p['source'].split(';')[0][:140]} ({p['verification']})", "url": p.get("url")}

    def clean(lst):
        return [x for x in lst if x]

    # ---------------- who pays
    def prog(fid, program, detail_fmt):
        f = facts.get(fid)
        if not usable(f):
            return None
        return {"program": program, "detail": detail_fmt(f) + ("" if f["verification"] == "primary" else " (secondary source; confirm before relying on it)"), "url": f["url"]}

    who_s1 = clean([
        prog("eqip_340_usd_ac", "NRCS EQIP practice 340 (Cover Crop)", lambda f: f"about ${f['value']:.0f}/acre (FY2026 Iowa, single species, regular rate); ${f['range']['hi']:.0f}/acre for historically underserved producers"),
        prog("idals_costshare_usd_ac", "IDALS cover crop cost-share", lambda f: f"${f['range']['hi']:.0f}/acre first-time, ${f['range']['lo']:.0f}/acre returning users, up to 160 acres"),
        prog("gdmw_costshare_usd_ac", "Greater Des Moines Watershed program (IDALS)", lambda f: f"${f['value']:.0f}/acre on up to 500 acres in the 22 participating counties, stackable with the state program; check whether your county is included"),
        prog("crop_insurance_discount_usd_ac", "Cover crop crop-insurance discount (IDALS + USDA-RMA)", lambda f: f"${f['value']:.0f}/acre off the premium, only on acres without other cover-crop cost-share"),
    ])
    e328 = facts.get("eqip_328_usd_ac")
    who_s2 = [{"program": "NRCS EQIP practice 328 (Conservation Crop Rotation)",
               "detail": (f"about ${e328['value']:.2f}/acre" if usable(e328) else "payment rate not verified yet; ask your NRCS field office") + "; CSP can also support resource-conserving rotations",
               "url": "https://www.nrcs.usda.gov/programs-initiatives/eqip-environmental-quality-incentives-program"}]
    who_s3 = [
        {"program": "USDA FSA Continuous CRP, practice CP-43 (prairie strips)", "detail": "annual rental payment plus establishment cost-share on the strip acres; ISU STRIPS reports this cuts the farmer's cost by roughly three-quarters (secondary, web summary)",
         "url": "https://www.fsa.usda.gov/programs-and-services/conservation-programs/conservation-reserve-program/"},
        {"program": "ISU STRIPS team (free planning help)", "detail": "site design, seed mixes and cost calculator", "url": "https://strips.nrem.iastate.edu/"},
    ]

    # ---------------- costs ($/acre)
    sc, sd_ = facts.get("rye_seeding_cost_usd_ac"), facts.get("rye_seed_cost_usd_ac")
    if usable(sc) and usable(sd_):
        plant_lo = sc["range"]["lo"] + sd_["range"]["lo"]
        plant_hi = sc["range"]["hi"] + sd_["range"]["hi"]
        cost_s1 = {"lo": round(plant_lo / 2, 1), "hi": round(plant_hi / 2, 1),
                   "per_planting": {"lo": plant_lo, "hi": plant_hi},
                   "basis": "per acre per year, averaged over the corn-soybean rotation (rye is planted every other fall); seed + custom drilling, termination pass not included",
                   "source": f"ISU custom rate survey (drilling ${sc['range']['lo']}-{sc['range']['hi']}) + ISU rye seed (${sd_['range']['lo']}-{sd_['range']['hi']})",
                   "url": sc["url"]}
    else:
        cost_s1 = {"lo": round(sc["range"]["lo"] / 2, 1), "hi": round(sc["range"]["hi"] / 2, 1), "basis": "drilling only (seed price not verified), per acre per year averaged over the rotation",
                   "source": "ISU custom rate survey", "url": sc["url"]}
    cost_s2 = {"lo": None, "hi": None, "basis": "not quantified",
               "source": "ISU Marsden trial: profit of the 4-yr system similar to or greater than corn-soy (2003-2011 prices, with manure); no verified $/acre for a farm switching today",
               "url": facts.get("extended_rotation_marsden", {}).get("url")}
    cost_s3 = {"lo": 24, "hi": 39, "basis": "per treated (whole-field) acre per year, mostly rent/income lost on the strip acres, before CRP payments",
               "source": "ISU STRIPS economics ($24-35 in the 2013 study, $28-39 in the 2017 edition); secondary (web search summary, not yet in facts.json)",
               "url": "https://strips.nrem.iastate.edu/chapter-5-economics", "verification": "secondary"}

    def pct(x):
        return f"{x:.0f}%"

    rye_old = f" (earlier INRS table: {rye['older']['mean']:.0f}%, SD {rye['older']['sd']:.0f})" if rye.get("older") else ""
    ext_old = f" (earlier INRS table: {ext['older']['mean']:.0f}%, SD {ext['older']['sd']:.0f})" if ext.get("older") else ""

    strategies = [
        {
            "id": "S0", "name": "Current corn-soybean (no cover)", "short": "Keep today's rotation: the reference every other option is compared to",
            "why": (f"This is what most fields here do now. Satellites show these fields bare about {bare_octmay:.0%} of the time from October to May. "
                    f"About {leak_octmay:.0%} of the modelled nitrate leak falls in those months, when rain and snowmelt drain through wet soil and no living roots take up nitrate."),
            "evidence": clean([
                fact_ev("isu_lbN_acre_yr", "Iowa State: an average Iowa corn or soybean acre loses about 30 lb nitrate-N a year (15-50 typical; corn and soybean years are similar)."),
                {"text": f"River-calibrated estimate for the Raccoon basin, 2016-2025: about {rac_mean_lb:.0f} lb N per row-crop acre per year reaches the Van Meter gauge (range by year shown on the field card). This is what is left after losses in ditches and streams, so the loss at the field edge is likely higher.",
                 "source": "Field to Faucet calibration to USGS 05484500 nitrate sensor + flow", "url": "https://waterdata.usgs.gov/monitoring-location/05484500/"},
            ]),
            "satellite_evidence": (f"NASA HLS (Landsat + Sentinel-2), 1,769 fields, 2020-2025: bare {bare_octmay:.0%} of Oct-May and {bare_aprjun:.0%} of Apr-Jun. "
                                   f"Winter living cover seen on {cover_pct:.1f}% of field-winters 2021-2026."),
            "n_loss_reduction": {"mean": 0.0, "lo": 0.0, "hi": 0.0, "source": "reference"},
            "yield_risk": {"level": "low", "text": "No change from what you do now."},
            "soil_health": [],
            "gaps": ["The field estimate is for a 40-acre grid square, not your surveyed field.",
                     "Your own N rate, timing, manure and tile layout are not known to the model."],
            "risks_local_review": ["Doing nothing keeps fall-to-spring nitrate losses where they are, and the most loss comes in wet years like 2016-2019 and 2024-2025."],
            "who_pays": [], "cost_usd_ac": {"lo": 0, "hi": 0, "source": "reference"},
        },
        {
            "id": "S1", "name": "Cereal rye before soybean", "short": "Drill rye after corn harvest; end it before or at soybean planting (every other winter)",
            "why": (f"Living rye roots take up nitrate in the months these fields sit bare. On the average field here, {leak_octmay:.0%} of the modelled leak falls October-May, "
                    f"and Apr-Jun gets {storms_aprjun:.0%} of the year's big-storm days. Rye before soybean is the lowest-risk niche: soybean yield is rarely hurt."),
            "evidence": clean([
                {"text": f"Iowa Nutrient Reduction Strategy (2024 science update): rye cuts nitrate-N in drainage by {pct(rye['mean'])} on average, SD {rye['sd']:.0f}{rye_old}. Very variable: it depends on how much rye grows.",
                 "source": f"INRS Science Team ({rye['verification']})", "url": rye["url"]},
                fact_ev("kaspar_rye_pct", "USDA-ARS 14-year tile-drainage experiment near Ames: rye cut nitrate load 57%."),
                fact_ev("kaspar_other_sites_pct", "Other Iowa sites: 15-48% lower nitrate with rye."),
                fact_ev("rye_before_soybean_yield", "Midwest trials 2019-2021: ending rye before, at or after soybean planting did not reduce soybean yield in 27 of 28 location-years."),
                prior_ev("E1_soy_yield_pfi"),
            ]),
            "satellite_evidence": (f"HLS sees a rye-like spring green-up (NDVI >= 0.30 in mid-March to early May) on only {cover_pct:.1f}% of field-winters here (2021-2026); "
                                   f"{any_cover:.0f}% of fields showed it at least once. The bare window it would fill is visible on each field's leak calendar."),
            "n_loss_reduction": {"mean": round(rye["mean"] / 100, 3), **nlr(r1),
                                 "source": f"INRS 2024 update {rye['mean']:.0f}% (SD {rye['sd']:.0f}, {rye['sd_label']}); applies in the soybean years only, so a corn-soy field keeps about half of this per year on average{rye_old}"},
            "yield_risk": {"level": "low", "text": "Before soybean: no yield loss in 27 of 28 Midwest location-years (2024), no detectable effect in 20 of 29 Iowa farmer strip trials and a gain in 8. Long-term adopters in a satellite study saw about 3.5% lower soybean yield, so manage termination well."},
            "soil_health": clean([
                pri.get("E1_erosion_kaspar2001") and "Less erosion: rye cut interrill erosion about half and rill erosion about 90% in a central Iowa test (Kaspar 2001).",
                pri.get("E1_infiltration_basche2019") and "More water soaks in: cover crops raised infiltration about 35% (meta-analysis, Basche & DeLonge 2019).",
                pri.get("E1_soc_he2025") and "Slowly more soil carbon: about +4% with grass covers (global meta-analysis, He et al. 2025).",
                pri.get("E1_n2o_parkin2016") and "Lower total N2O (via less nitrate leaving) in a 10-year central Iowa study (Parkin 2016).",
            ]),
            "gaps": ["How much rye grows on your field each year (fall seeding date, winter, spring termination date) sets most of the benefit; the trial range is wide.",
                     "Satellite cover detection misses small rye that never reaches NDVI 0.30, so true adoption may be a bit higher than shown.",
                     "Rye every winter (also before corn) roughly doubles the N kept, but corn after rye needs careful N and termination management."],
            "risks_local_review": ["Termination timing and method (herbicide, roller) before or at soybean planting.",
                                   "Seed availability and a seeding window right after corn harvest (drill vs. aerial).",
                                   "Herbicide carryover from the corn year can hurt rye establishment.",
                                   "Cash flow: seed and seeding are paid in fall, cost-share comes later.",
                                   "Crop-insurance rules for cover crop termination (NRCS/RMA guidelines)."],
            "who_pays": who_s1, "cost_usd_ac": cost_s1,
        },
        {
            "id": "S2", "name": "Extended rotation: corn-soybean-oats-alfalfa (4 years)", "short": "Add oats seeded with alfalfa, then a full alfalfa year, to the corn-soy rotation",
            "why": (f"Oats, then alfalfa, keep living roots in the soil for about two of four years, including the fall and spring months when these fields now sit bare "
                    f"({bare_octmay:.0%} of Oct-May on average). Alfalfa also supplies N to the next corn crop, so less fertilizer is bought."),
            "evidence": clean([
                {"text": f"INRS 2024 science update: an extended rotation of 4 or more years cuts nitrate-N in drainage by {pct(ext['mean'])} on average, SD {ext['sd']:.0f}{ext_old}. A 3-year corn-soy-small grain rotation is lower: {pct(ext3['mean'])} (SD {ext3['sd']:.0f}).",
                 "source": f"INRS Science Team ({ext['verification']})", "url": ext["url"]},
                fact_ev("extended_rotation_marsden", "ISU Marsden trial (2003-2011): 3- and 4-year rotations with far less synthetic N and herbicide had grain yields and profit similar to or greater than corn-soy."),
                prior_ev("E4_corn_yield_davis2012"), prior_ev("E4_soy_yield_davis2012"),
            ]),
            "satellite_evidence": "HLS: alfalfa and oat/clover fields stay green from April to October and regrow in fall; in this area almost no field shows that pattern today (the fields here are corn or soybean in at least 7 of 10 years, CDL).",
            "n_loss_reduction": {"mean": round(ext["mean"] / 100, 3), **nlr(r2), "source": f"INRS 2024 update, 4+ yr rotation {ext['mean']:.0f}% (SD {ext['sd']:.0f}, {ext['sd_label']}){ext_old}"},
            "yield_risk": {"level": "moderate", "text": "Corn and soybean yields were similar or higher in the Marsden trial (about +4% corn, +9% soybean), but you grow oats and alfalfa two years in four, so income depends on hay and oat markets or livestock."},
            "soil_health": clean([
                pri.get("E4_nfert_davis2012") and "Much less bought N: synthetic N use fell 80-86% in the Marsden diverse rotations (with manure).",
                pri.get("E4_herbicide_davis2012") and "Herbicide use fell 88% with equal weed control (Marsden).",
                pri.get("E4_drought_bowles2020") and "More stable corn yields in drought: diverse rotations cut drought-year losses 14-90% across North American sites (Bowles 2020).",
                "Can interrupt corn-soybean pest cycles (no trial number in our evidence set; ask your agronomist how much for your field).",
            ]),
            "gaps": ["INRS numbers come from rotations with at least 2 years of alfalfa; a 3-year version with oats/red clover is much less certain (15%, SD 34).",
                     "Local markets for oats, straw and hay, and whether livestock are nearby, are not in the model.",
                     "The Marsden profit result used manure and 2003-2011 prices."],
            "risks_local_review": ["Hay equipment, storage and labor for alfalfa.",
                                   "Buyer or livestock outlet for oats and hay.",
                                   "Alfalfa stand termination before corn and the N credit to use.",
                                   "Lease terms, base acres and crop insurance for small grains and hay.",
                                   "Cash flow during the switch-over years."],
            "who_pays": who_s2, "cost_usd_ac": cost_s2,
        },
        {
            "id": "S3", "name": f"Prairie on about {strip_frac:.0%} of the field", "short": "Plant native prairie strips (or retire the wettest corner) on about a tenth of the field",
            "why": ("Perennial prairie has living roots all year. The INRS land-retirement (CRP) efficiency applies to the converted acres. On tile-drained ground, most tile water passes under strips, "
                    "so we count only the converted area; the measured big wins are less erosion, phosphorus and runoff."),
            "evidence": clean([
                {"text": f"INRS: land retirement (CRP) cuts nitrate-N by {pct(crp['mean'])} (SD {crp['sd']:.0f}) on the converted land; no new data in the 2024 update.", "source": f"INRS ({crp['verification']})", "url": crp["url"]},
                fact_ev("prairie_strips_nitrate", "ISU STRIPS (Schulte et al. 2017): about 10% prairie in small non-tiled watersheds cut groundwater nitrate about 72% and runoff total N about 70%. Not tile drainage, so not directly comparable."),
                prior_ev("E3_sediment_schulte2017"), prior_ev("E3_yield_schulte2017"),
            ]),
            "satellite_evidence": "HLS would show a strip that stays green from April to November; the field leak calendar shows where the bare-and-wet months are, but a 40-acre square cannot show which part of your field is wettest.",
            "n_loss_reduction": {"mean": round(strip_frac * crp["mean"] / 100, 3), **nlr(strip_frac * r3),
                                 "source": f"whole-field effect = {strip_frac:.0%} converted x INRS CRP {crp['mean']:.0f}% (SD {crp['sd']:.0f}); assumes the converted strip leaked like the field average"},
            "yield_risk": {"level": "low", "text": "Yield on the cropped 90% was unchanged in the ISU STRIPS watersheds; you give up the crop on the strip acres (counted in the cost)."},
            "soil_health": clean([
                pri.get("E3_sediment_schulte2017") and "Sediment export cut about 95% (ISU STRIPS).",
                pri.get("E3_tp_schulte2017") and "Total phosphorus in runoff cut about 77%.",
                pri.get("E3_runoff_schulte2017") and "Total runoff cut about 37%.",
            ]),
            "gaps": ["The model cannot see which 10% of a 40-acre square is the wettest or leakiest; putting prairie over a tile outlet area or wet depression may keep more N than shown.",
                     "Prairie strips are not an INRS tile-drainage practice; the nitrate number on tile-drained land is uncertain.",
                     "For tile water itself, edge-of-field practices (saturated buffers 45%, bioreactors 24% of treated drainage in the 2024 update) are the INRS options to ask about."],
            "risks_local_review": ["Where strips go relative to tile lines, waterways and slope.",
                                   "Establishment takes more than one season, with weed control (usually mowing) early on; ask the STRIPS team or NRCS for your site.",
                                   "CRP contract length and rules (haying/grazing limits).",
                                   "Lost income on the strip acres; landlord agreement if rented."],
            "who_pays": who_s3, "cost_usd_ac": cost_s3,
        },
    ]
    sj = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strategies": strategies,
        "disclaimer": DISCLAIMER,
        "method": ("Field leak (lb N/acre/yr) = satellite-seen bare ground x wet-soil drainage (NASA POWER) x soil drainage class, calibrated each year so all fields "
                   "and sub-watersheds add up to the nitrate load measured by USGS at Van Meter / Des Moines. Ranges: 10th-90th percentile over 2016-2025 weather years, "
                   "the calibration uncertainty and the trial range of each practice. Fertilizer value uses " + price_src + "; it is an upper bound because the next crop "
                   "does not recover all retained N. Leak and N kept are counted as nitrate that would have reached the river gauge; some nitrate is removed in ditches and streams on the way, so the N kept at the field edge is likely larger than shown."),
        "units": {"lbN_kept_ac": "lb N per acre per year, averaged over the rotation", "cost_usd_ac": "see each strategy's cost basis"},
    }
    (OUT / "strategies.json").write_text(json.dumps(sj, indent=1))

    # ---------------- field_detail.json
    log("field_detail")
    years = [c for c in fs.columns if re.fullmatch(r"lbN_ac_\d{4}", c)]
    fd = {}
    for i, r in enumerate(fs.itertuples()):
        lsh = np.array(r.cal_leak_share)
        ks = {k: {"lbN_kept_ac": {"p10": rnd(kq[k][0, i]), "p50": rnd(kq[k][1, i]), "p90": rnd(kq[k][2, i]), "mean": rnd(kmean[k][i])},
                  "fert_value_usd_ac": {"p10": rnd(fq[k][0, i], 2), "p50": rnd(fq[k][1, i], 2), "p90": rnd(fq[k][2, i], 2), "mean": rnd(fmean[k][i], 2)}} for k in kept}
        if freq_cs[i] == 0:
            ks["S1"]["note"] = "No soybean-after-corn years in this field's 2016-2025 history, so rye before soybean does not apply as is."
        bare_ = np.array(r.cal_bare_frac)
        why_field = (f"{r.frac_leak_oct_may:.0%} of this field's modelled leak falls October-May, when it was bare {bare_[octmay].mean():.0%} of the time; "
                     f"{r.frac_leak_apr_jun:.0%} falls April-June.")
        fd[r.field_id] = {
            "seq": r.seq, "crop_2025": r.crop_2025, "drainage": r.drainage, "slope_pct": rnd(r.slope_pct, 2),
            "leak": {"lbN_ac_yr": {"p10": rnd(r.leak_lbN_ac_yr_p10), "p50": rnd(r.leak_lbN_ac_yr_p50), "p90": rnd(r.leak_lbN_ac_yr_p90), "mean": rnd(lmean[i])},
                     "by_year": {c[-4:]: rnd(getattr(r, c)) for c in years}},
            "calendar": {"months": list(range(1, 13)),
                         "bare_frac": [rnd(v, 2) for v in r.cal_bare_frac], "rain_mm": [rnd(v, 0) for v in r.cal_rain_mm],
                         "storm_days": [rnd(v, 2) for v in r.cal_storm_days], "wetness": [rnd(v, 3) for v in r.cal_wetness],
                         "leak_risk": [rnd(v, 2) for v in r.cal_leak_risk], "leak_share": [rnd(v, 3) for v in lsh],
                         "interp_only": [bool(v) for v in r.cal_interp_only],
                         "interp_only_share": [rnd(v, 2) for v in r.cal_interp_only_share]},
            "ndvi_recent": {"dates": list(r.ndvi_dates), "ndvi": [rnd(v, 2) for v in r.ndvi_vals]},
            "cover_years": json.loads(r.cover_years_json),
            "strategies": ks,
            "why_field": why_field,
        }
    (OUT / "field_detail.json").write_text(json.dumps(fd, separators=(",", ":")))
    size = (OUT / "field_detail.json").stat().st_size / 1e6

    summ = {k: {"p10_of_field_p50": rnd(np.percentile(kq[k][1], 10)), "median_field_p50": rnd(np.median(kq[k][1])), "p90_of_field_p50": rnd(np.percentile(kq[k][1], 90)),
                "median_field_p10": rnd(np.median(kq[k][0])), "median_field_p90": rnd(np.median(kq[k][2])),
                "median_fert_usd_p50": rnd(np.median(fq[k][1]), 2), "median_field_mean": rnd(np.median(kmean[k])),
                "median_fert_usd_mean": rnd(np.median(fmean[k]), 2)} for k in kept}
    summ["leak"] = {"median_field_mean": rnd(np.median(lmean)), "median_field_p50": rnd(float(fs["leak_lbN_ac_yr_p50"].median()))}
    log("N kept (lb/ac/yr) summary:", json.dumps(summ))
    log(f"field_detail.json {size:.1f} MB, {len(fd)} fields; done in {time.time() - t0:.0f}s")
    return summ


if __name__ == "__main__":
    main()
