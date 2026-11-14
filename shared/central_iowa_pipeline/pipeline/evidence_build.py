"""evidence module: build data/evidence_priors.json.

The priors below were compiled by hand from the cited papers (web research, Nov 2026). Every number is
taken from the source named in the same record; `verification` says how it was checked:
  - "full_text"  : the number was read in the paper's full text (PDF/HTML) during compilation
  - "abstract"   : the number was read in the official abstract / publisher landing page
  - "secondary"  : the number comes from an extension publication, press release or search-engine
                   extraction of the publisher page; the original could not be opened (paywall/403)
Derived numbers (e.g. fold-change -> percent change) are flagged with `derived: true` and the formula.

Strategy IDs here are EVIDENCE IDs E1..E5, deliberately distinct from the web card IDs S0..S3 in
web/data/effects.json. `WEB_STRATEGY_MAP` (also written to the JSON as `web_strategy_map`) and the per-prior
`web_strategy_id` say which web card a prior can inform:
  E1 rye -> S1 (web card = rye before soybean; before_corn priors get variant_mismatch=true)
  E2 no-till -> S2;  E3 prairie strips -> null (no web card);  E4 extended rotation -> S3;  E5 CS vs CC -> S3
Only priors with prior_kind == "numeric" have a usable effect.mean.

shock_years is filled from the US Drought Monitor county statistics fetched by pipeline/evidence_usdm.py
(run that first; this script re-runs it automatically if its output is missing).

Re-run: .venv/bin/python pipeline/evidence_build.py
"""
import datetime as dt
import json
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "evidence_priors.json")
USDM_DIR = os.path.join(ROOT, "data", "raw", "usdm")


def fold_to_pct(f):
    """'X times lower' -> percent change of treatment vs control."""
    return round((1.0 / f - 1.0) * 100.0, 1)


STRATEGIES = {
    "E1": {"name": "Cereal rye winter cover crop", "variants": ["before_soybean", "before_corn"],
           "web_card": "S1 (web card is rye before soybean only; before_corn priors carry variant_mismatch=true)"},
    "E2": {"name": "Reduced tillage / no-till vs conventional (chisel/moldboard) tillage", "variants": ["no_till", "strip_till"], "web_card": "S2"},
    "E3": {"name": "Prairie strips (10-20% of field in contour/footslope native prairie)", "variants": ["10pct_strips"], "web_card": None},
    "E4": {"name": "Extended rotation (corn-soybean-small grain/red clover or alfalfa) vs corn-soybean", "variants": ["3yr", "4yr"], "web_card": "S3 (corn-soy-oats(+clover) branch for corn-soy fields)"},
    "E5": {"name": "Corn-soybean rotation vs continuous corn (rotation benefit)", "variants": ["cs_vs_cc"], "web_card": "S3 (corn-soy branch for continuous-corn fields)"},
}

# outcome keys: yield_pct, yield_t_ha, sediment_pct, soil_loss_pct, interrill_erosion_pct, rill_erosion_pct,
# runoff_pct, infiltration_pct, nitrate_leach_pct, nitrate_conc_pct, total_n_runoff_pct, total_p_runoff_pct,
# n2o_pct, soc_pct, soc_t_c_ha_yr, n_fert_pct, herbicide_pct, drought_yield_loss_reduction_pct,
# prevented_planting_indemnity_usd, a_horizon_loss_area_pct, tillage_translocation_t_ha_yr
# web_key: the effects.json outcome this prior can inform (null if none)

P = []


WEB_STRATEGY_MAP = {"E1": "S1", "E2": "S2", "E3": None, "E4": "S3", "E5": "S3"}
WEB_VARIANT_NOTE = {
    "E1": "web S1 = cereal rye before soybean",
    "E2": "web S2 = reduced tillage / no-till",
    "E4": "web S3 'Diversify', corn-soy-oats(+clover) branch for corn-soy fields",
    "E5": "web S3 'Diversify', corn-soy branch for continuous-corn fields",
}
PRIOR_KINDS = ("numeric", "counts", "range", "qualitative")


def add(**kw):
    kw.setdefault("derived", False)
    kw.setdefault("use_as_prior", True)
    kw.setdefault("prior_kind", "numeric")
    P.append(kw)


def finalize(p):
    """Attach web mapping and unit-compatibility fields; enforce consistency rules."""
    sid = p["strategy_id"]
    p["web_strategy_id"] = WEB_STRATEGY_MAP[sid]
    p["variant_mismatch"] = bool(sid == "E1" and p["variant"] == "before_corn")
    p["web_variant_note"] = WEB_VARIANT_NOTE.get(sid, "no web card for this evidence strategy")
    if p["variant_mismatch"]:
        p["web_variant_note"] += "; this prior is rye BEFORE CORN, so it is context for the web card, not a direct estimate"
    if p.get("web_key") is None:
        # null unless the record names a conversion that would let phase2 fill a web outcome (e.g. Kluger 2022 t/ha)
        p.setdefault("web_unit_compatible", None)
        p.setdefault("conversion", None)
    elif "web_unit_compatible" not in p and p["prior_kind"] != "numeric":
        p["web_unit_compatible"] = False
        p["conversion"] = f"not convertible: {p['prior_kind']} record (no mean); context for the {p['web_key']} outcome only"
    elif "web_unit_compatible" not in p:
        # yield_pct / nitrate_pct / n2o_pct priors that are already % change of treatment vs control
        assert p["web_key"] in ("yield_pct", "nitrate_pct", "n2o_pct"), p["prior_id"]
        assert p["effect"]["unit"].startswith("%"), p["prior_id"]
        p["web_unit_compatible"] = True
        p["conversion"] = "none: already % change of treatment vs control"
    assert p["prior_kind"] in PRIOR_KINDS, p["prior_id"]
    if p["prior_kind"] == "numeric":
        assert p["effect"]["mean"] is not None, p["prior_id"]
    else:
        assert p["effect"]["mean"] is None and not p["use_as_prior"], p["prior_id"]
    if p["use_as_prior"]:
        assert p["effect"]["mean"] is not None, p["prior_id"]
    if p["derived"]:
        assert p.get("derivation"), p["prior_id"]


# ----------------------------------------------------------------------------------------------- E1 cereal rye
add(prior_id="E1_soy_yield_pfi", strategy_id="E1", variant="before_soybean", outcome="yield_trial_counts", web_key="yield_pct",
    effect={"mean": None, "unit": "count of strip trials", "detail": {"soy_trials": 29, "no_effect": 20, "yield_increase": 8, "other": 1}},
    uncertainty={"se": None, "ci95": None, "note": "per-trial significance only; pooled mean not reported"},
    n={"trials": 29, "farms": 12, "years": "2009-2018 (approx., study started fall 2008)"},
    design="on-farm replicated strip trials (farmer cooperators, randomized paired strips)",
    region="Iowa (statewide cooperator farms)",
    source="Practical Farmers of Iowa & Iowa Learning Farms long-term winter cereal rye cooperator study, summarized in Gailans S. (2019) 'Using Science & On-Farm Research to Investigate Cover Crops in Iowa', PFI",
    url="https://practicalfarmers.org/resources/articles/using-science-on-farm-research-to-investigate-cover-crops-in-iowa/",
    summary="Over ~10 years, rye before soybean had no detectable yield effect in 20 of 29 trials and raised soybean yield in 8.",
    applicability="Directly applicable to central Iowa corn-soy; supports a prior centred near zero (slightly positive) for soybean after well-managed rye. Earlier 5-yr report (2009-2013): rye raised soy yield in 4 of 18 trials, little/no negative effect in 13.",
    prior_kind="counts", use_as_prior=False, verification="secondary")

add(prior_id="E1_soy_yield_pantoja", strategy_id="E1", variant="before_soybean", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 0.2, "unit": "% change soybean yield (59.1 vs 59.0 bu/ac)"},
    uncertainty={"se": None, "ci95": None, "note": "reported as not significant"},
    n={"sites": 4, "years": "2009-2011 (farm report extends to 2013)"},
    design="randomized replicated plot experiment (no-till corn-soybean, +/- rye, 6 N rates)",
    region="Iowa (4 ISU research farms incl. central Iowa)",
    source="Pantoja J.L., Woli K.P., Sawyer J.E., Barker D.W. (2015) Corn nitrogen fertilization requirement and corn-soybean productivity with a rye cover crop. Soil Sci. Soc. Am. J. 79(5):1482-1495; ISU Research Farm Report (2014) for the bu/ac values",
    url="https://www.agronext.iastate.edu/soilfertility/info/2009-2013CoverCrop-NFertilization_ResearchFarmReport_3-7-14.pdf",
    doi="10.2136/sssaj2015.02.0084",
    summary="Rye cover crop did not affect soybean yield in Iowa no-till plots.",
    applicability="Iowa no-till plots; tile drainage and termination timing match typical central Iowa practice.",
    verification="full_text", derived=True, derivation="(59.1/59.0 - 1)*100",
    notes="bu/ac values read in the ISU Research Farm Report full text (2009-2013, all sites: 'soybean yield was not affected by the rye cover crop'). DOI, volume and pages verified via Crossref.")

add(prior_id="E1_soy_yield_deines", strategy_id="E1", variant="before_soybean", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -3.5, "unit": "% change soybean yield on fields with >=3 yr cover crops"},
    uncertainty={"se": None, "ci95": None, "note": "CI not retrieved"},
    n={"fields": ">90,000 (corn+soy)", "years": "2019-2020"},
    design="observational (satellite yield + causal forest)",
    region="US Midwest (6 states incl. Iowa)",
    source="Deines J.M., Guan K., Lopez B., Zhou Q., White C.S., Wang S., Lobell D.B. (2023) Recent cover crop adoption is associated with small maize and soybean yield losses in the United States. Global Change Biology 29(3):794-807",
    url="https://doi.org/10.1111/gcb.16489", doi="10.1111/gcb.16489",
    summary="Observational contrast: fields with 3+ years of cover crops had ~3.5% lower soybean yield.",
    applicability="Same method family as COUNTERFIELD; use as contrast/upper bound on harm, not as a trial prior. Losses larger with warm June and dry spring.",
    use_as_prior=False, verification="abstract",
    notes="DOI, volume and pages verified via Crossref.")

add(prior_id="E1_corn_yield_pfi", strategy_id="E1", variant="before_corn", outcome="yield_trial_counts", web_key="yield_pct",
    effect={"mean": None, "unit": "count of strip trials", "detail": {"corn_trials": 39, "no_effect": 32, "yield_reduction_or_other": 7}},
    uncertainty={"se": None, "ci95": None},
    n={"trials": 39, "farms": 12, "years": "~2009-2018"},
    design="on-farm replicated strip trials",
    region="Iowa", source="PFI & Iowa Learning Farms cereal rye cooperator study (Gailans 2019, PFI)",
    url="https://practicalfarmers.org/resources/articles/using-science-on-farm-research-to-investigate-cover-crops-in-iowa/",
    summary="Rye before corn had no detectable effect in 32 of 39 trials; reductions mostly occurred in the first two years.",
    applicability="Yield drag before corn is attributed by farmers to termination/planting-into-residue problems; PFI planting-green corn trials (2016-2018) lost ~14 bu/ac.",
    prior_kind="counts", use_as_prior=False, verification="secondary")

add(prior_id="E1_corn_yield_pantoja", strategy_id="E1", variant="before_corn", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -4.6, "unit": "% change corn yield at economic optimum N rate (2009-2013, all sites; 179 vs 188 bu/ac)",
            "bu_ac_at_eonr": {"rye": 179, "no_rye": 188}, "all_n_rates_pct": -7.6,
            "reported_sssaj_2015_pct": -6.0, "reported_sssaj_2015_note": "2009-2011 subset, peer-reviewed abstract"},
    uncertainty={"se": None, "ci95": None, "note": "no SE/CI reported; SSSAJ 2015 (2009-2011) gives -6%, ISU report (2009-2013) gives -4.6%; ICM 2017 summary: -5%"},
    n={"sites": 4, "years": "2009-2013 (SSSAJ paper covers 2009-2011)"},
    design="randomized replicated plot experiment",
    region="Iowa (4 ISU research farms)",
    source="Pantoja J.L., Woli K.P., Sawyer J.E., Barker D.W. (2015) Soil Sci. Soc. Am. J. 79(5):1482-1495; ISU Research Farm Report (2014) for the 2009-2013 bu/ac values",
    url="https://doi.org/10.2136/sssaj2015.02.0084", doi="10.2136/sssaj2015.02.0084",
    report_url="https://www.agronext.iastate.edu/soilfertility/info/2009-2013CoverCrop-NFertilization_ResearchFarmReport_3-7-14.pdf",
    summary="Rye reduced corn yield ~4.6% at the economic optimum N rate over 2009-2013 (-6% in the 2009-2011 peer-reviewed subset); N rate recommendation unchanged.",
    applicability="Best Iowa-specific trial prior for rye before corn: about -5% (range -4.6 to -6%). The web S1 card is rye before soybean, so this is variant_mismatch context for that card.",
    verification="full_text", notes="-4.6% and 179/188 bu/ac read in the ISU Research Farm Report full text; -6% from the SSSAJ abstract. Same paper and DOI as E1_soy_yield_pantoja.")

add(prior_id="E1_corn_yield_marcillo", strategy_id="E1", variant="before_corn", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 0.0, "unit": "% change corn yield, grass (non-legume) cover crops"},
    uncertainty={"se": None, "ci95": None, "note": "reported as no significant effect for grass covers; legume +21%, mixtures +13% (as summarized by Thapa et al. 2018)"},
    n={"studies": 65, "years": "1965-2015 literature"},
    design="meta-analysis of field experiments (US & Canada)",
    region="US & Canada",
    source="Marcillo G.S., Miguez F.E. (2017) Corn yield response to winter cover crops: An updated meta-analysis. J. Soil Water Conserv. 72(3):226-239",
    url="https://doi.org/10.2489/jswc.72.3.226", doi="10.2489/jswc.72.3.226",
    summary="Grass cover crops such as rye neither raised nor lowered corn yield on average; legumes and mixtures raised it.",
    applicability="Broad prior (wide climate range); combine with the Iowa-specific Pantoja estimate.",
    verification="secondary", notes="Effect sizes per Thapa et al. 2018 JEQ (full text read) citing this paper; DOI verified via Crossref.")

add(prior_id="E1_corn_yield_deines", strategy_id="E1", variant="before_corn", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -5.5, "unit": "% change corn yield on fields with >=3 yr cover crops"},
    uncertainty={"se": None, "ci95": None},
    n={"fields": ">90,000", "years": "2019-2020"}, design="observational (satellite + causal forest)",
    region="US Midwest", source="Deines et al. (2023) Global Change Biology 29(3):794-807",
    url="https://doi.org/10.1111/gcb.16489", doi="10.1111/gcb.16489",
    summary="Observational contrast: ~5.5% lower corn yield after 3+ years of cover crops; larger on better soils and with dry springs.",
    applicability="Contrast only.", use_as_prior=False, verification="abstract")

add(prior_id="E1_yield_he2025_us", strategy_id="E1", variant="both", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -3.1, "unit": "% change main-crop yield, United States subset"},
    uncertainty={"se": None, "ci95": None, "note": "global non-legume yield effect not significant (p=0.69)"},
    n={"studies": 271, "observations": 3160}, design="global meta-analysis",
    region="Global (US subset reported in discussion)",
    source="He Q., Lu C., Cowie A. et al. (2025) Optimizing cover cropping application for sustainable crop production. npj Sustainable Agriculture 3:10",
    url="https://doi.org/10.1038/s44264-025-00050-8", doi="10.1038/s44264-025-00050-8",
    summary="Non-legume covers had no significant global yield effect; the US mean was a ~3% loss.",
    applicability="Context; non-legumes reduce yield in temperate regions such as the US Midwest.", verification="full_text")

add(prior_id="E1_erosion_kaspar2001", strategy_id="E1", variant="before_soybean_and_corn", outcome="interrill_erosion_pct", web_key="erosion_t_ac",
    effect={"mean": -54.0, "unit": "% change interrill erosion (rye vs no cover, no-till soybean residue)", "rill_erosion_pct": -90.0,
            "oat_interrill_pct": -26.0, "oat_rill_pct": -65.0},
    uncertainty={"se": None, "ci95": None, "note": "interrill reduction significant in 2 of 3 rainfall-simulation years"},
    n={"site_years": 3}, design="randomized plot rainfall-simulation experiment",
    region="central Iowa (4.4% slope, no-till soybean)",
    source="Kaspar T.C., Radke J.K., Laflen J.M. (2001) Small grain cover crops and wheel traffic effects on infiltration, runoff, and erosion. J. Soil Water Conserv. 56(2):160-164; percentages as reported in ISU Extension PM 1999",
    url="https://store.extension.iastate.edu/Product/pm1999-pdf", doi="10.1080/00224561.2001.12457370",
    web_unit_compatible=False, conversion="relative change: erosion_t_ac_treated = phase2 baseline erosion_t_ac x (1 + mean/100); applies on top of no-till residue",
    summary="Rye cut interrill erosion about half and rill erosion about 90% versus no-till without a cover crop.",
    applicability="Directly relevant to the erosion_index; effect is on top of no-till residue (78% cover).", verification="secondary")

add(prior_id="E1_nitrate_thapa2018", strategy_id="E1", variant="before_soybean_and_corn", outcome="nitrate_leach_pct", web_key="nitrate_pct",
    effect={"mean": -56.0, "unit": "% change NO3- leaching, non-legume cover vs none"},
    uncertainty={"se": None, "ci95": [-66.0, -43.0]},
    n={"studies": 28, "observations": 238}, design="global meta-analysis of field experiments",
    region="Global (includes Iowa tile-drainage studies Kaspar 2007, 2012)",
    source="Thapa R., Mirsky S.B., Tully K.L. (2018) Cover crops reduce nitrate leaching in agroecosystems: a global meta-analysis. J. Environ. Qual. 47(6):1400-1411",
    url="https://www.ars.usda.gov/ARSUserFiles/21904/Others%20PDFs/J%20Environ%20Qual%2047p1400.pdf", doi="10.2134/jeq2018.03.0107",
    summary="Non-legume covers such as rye cut nitrate leaching by about 56% on average.",
    applicability="Modelled (striped) nitrate outcome. Larger effect with earlier planting and more biomass, coarse soils and drier years.",
    verification="full_text")

add(prior_id="E1_nitrate_kaspar2007", strategy_id="E1", variant="before_soybean_and_corn", outcome="nitrate_load_pct", web_key="nitrate_pct",
    effect={"mean": -61.0, "unit": "% change NO3 load in tile drainage", "flow_weighted_conc_pct": -59.0},
    uncertainty={"se": None, "ci95": None, "note": "significant in all 4 years; drainage volume not reduced"},
    n={"years": 4, "period": "2002-2005"}, design="replicated drained field plots (long-term experiment)",
    region="central Iowa", source="Kaspar T.C., Jaynes D.B., Parkin T.B., Moorman T.B. (2007) Rye cover crop and gamagrass strip effects on NO3 concentration and load in tile drainage. J. Environ. Qual. 36:1503-1511",
    url="https://doi.org/10.2134/jeq2006.0468", doi="10.2134/jeq2006.0468",
    summary="Rye cut tile-drainage nitrate concentration 59% and load 61% in a central Iowa corn-soy system.",
    applicability="Directly applicable (tile-drained central Iowa corn-soy).", verification="abstract")

add(prior_id="E1_nitrate_kaspar2012", strategy_id="E1", variant="before_soybean_and_corn", outcome="nitrate_conc_pct", web_key="nitrate_pct",
    effect={"mean": -48.0, "unit": "% change flow-weighted NO3 concentration in tile drainage (5-yr)", "oat_pct": -26.0},
    uncertainty={"se": None, "ci95": None, "note": "load reductions not significant due to plot drainage variability"},
    n={"years": 5}, design="replicated drained field plots",
    region="central Iowa", source="Kaspar T.C., Jaynes D.B., Parkin T.B., Moorman T.B., Singer J.W. (2012) Effectiveness of oat and rye cover crops in reducing nitrate losses in drainage water. Agric. Water Manage. 110:25-33",
    url="https://doi.org/10.1016/j.agwat.2012.03.010", doi="10.1016/j.agwat.2012.03.010",
    summary="Over 5 years rye cut drainage nitrate concentration ~48% (oat ~26%).", applicability="Directly applicable.", verification="abstract")

add(prior_id="E1_n2o_parkin2016", strategy_id="E1", variant="before_soybean_and_corn", outcome="n2o_pct", web_key="n2o_pct",
    effect={"mean": -12.7, "unit": "% change total (direct+indirect) N2O over 10 yr (55.7 vs 63.8 kg N2O-N/ha)",
            "indirect_kg_n2o_n_ha_yr": {"rye": 1.25, "no_rye": 2.69}},
    uncertainty={"se": None, "ci95": None, "note": "total not significant (P=0.155); direct not significant; indirect significant (P=0.046)"},
    n={"years": 10, "period": "2004-2012 chamber measurements"}, design="long-term replicated field experiment",
    region="central Iowa", derived=True, derivation="(55.7/63.8 - 1)*100",
    source="Parkin T.B., Kaspar T.C., Jaynes D.B., Moorman T.B. (2016) Rye cover crop effects on direct and indirect nitrous oxide emissions. Soil Sci. Soc. Am. J. 80:1551-1559",
    url="https://doi.org/10.2136/sssaj2016.04.0120", doi="10.2136/sssaj2016.04.0120",
    summary="In central Iowa rye did not significantly change direct N2O; lower nitrate leaching cut estimated indirect N2O.",
    applicability="Best local prior: N2O effect ~0 (direct), modest reduction via indirect pathway; mark as modelled.",
    verification="abstract", notes="DOI/volume/pages verified via Crossref; numbers from abstract.")

add(prior_id="E1_n2o_basche2014", strategy_id="E1", variant="both", outcome="n2o_log_response_ratio", web_key="n2o_pct",
    effect={"mean": None, "unit": "log response ratio N2O flux", "detail": "40% of observations negative, 60% positive; full-year measurements near zero; legumes higher at low N"},
    uncertainty={"se": None, "ci95": None}, n={"articles": 26, "observations": 106}, design="meta-analysis",
    region="Global (temperate)", source="Basche A.D., Miguez F.E., Kaspar T.C., Castellano M.J. (2014) Do cover crops increase or decrease nitrous oxide emissions? A meta-analysis. J. Soil Water Conserv. 69(6):471-482",
    url="https://core.ac.uk/download/189483146.pdf", doi="10.2489/jswc.69.6.471",
    summary="Cover crop effects on N2O are mixed; whole-year measurements average near zero and non-legumes do better than legumes.",
    applicability="Supports a near-zero N2O prior for rye.", prior_kind="qualitative", use_as_prior=False, verification="abstract")

add(prior_id="E1_n2o_he2025", strategy_id="E1", variant="both", outcome="n2o_pct", web_key="n2o_pct",
    effect={"mean": None, "unit": "% change N2O, non-legume covers", "detail": "not significant (p=0.06); legume +36.2% (15.5 to 60.7)"},
    uncertainty={"se": None, "ci95": None}, n={"studies": 271, "observations": 3160}, design="global meta-analysis",
    region="Global", source="He et al. (2025) npj Sustainable Agriculture 3:10",
    url="https://doi.org/10.1038/s44264-025-00050-8", doi="10.1038/s44264-025-00050-8",
    summary="Non-legume covers had no significant N2O effect globally; legumes raised N2O by about a third.",
    applicability="Consistent with a near-zero prior for rye.", prior_kind="qualitative", use_as_prior=False, verification="full_text")

add(prior_id="E1_soc_he2025", strategy_id="E1", variant="both", outcome="soc_pct", web_key=None,
    effect={"mean": 4.0, "unit": "% change SOC, non-legume covers"}, uncertainty={"se": None, "ci95": [1.5, 6.7]},
    n={"studies": 271, "observations": 3160}, design="global meta-analysis", region="Global",
    source="He et al. (2025) npj Sustainable Agriculture 3:10", url="https://doi.org/10.1038/s44264-025-00050-8",
    doi="10.1038/s44264-025-00050-8", summary="Non-legume covers raised SOC by about 4%.",
    applicability="Smaller gains in cool temperate regions (per the paper).", verification="full_text")

add(prior_id="E1_infiltration_basche2019", strategy_id="E1", variant="both", outcome="infiltration_pct", web_key=None,
    effect={"mean": 34.8, "unit": "% change steady-state infiltration rate, cover crops vs conventional"},
    uncertainty={"se": 7.7, "ci95": [19.7, 49.9], "note": "SE from paper; CI derived as mean +/- 1.96*SE"},
    derived=True, derivation="ci95 = mean +/- 1.96*SE",
    n={"studies": 23, "paired_comparisons": 81}, design="global meta-analysis of field trials",
    region="Global", source="Basche A.D., DeLonge M.S. (2019) Comparing infiltration rates in soils managed with conventional and alternative farming methods: A meta-analysis. PLoS ONE 14(9):e0215702",
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC6752860/", doi="10.1371/journal.pone.0215702",
    summary="Cover crops raised infiltration by about 35% (verified: 34.8 +/- 7.7%).",
    applicability="Mechanism for drought/wet-year resilience and lower runoff. Note: Kaspar 2001 found rye raised infiltration in only 1 of 3 Iowa years.",
    verification="full_text")

add(prior_id="E1_prevented_planting_won2024", strategy_id="E1", variant="both", outcome="prevented_planting_indemnity_usd", web_key=None,
    effect={"mean": -38.69e6, "unit": "USD change in 2019 national prevented-planting indemnities per +1 percentage point county cover crop adoption",
            "loss_ratio_change": "4.47% -> 4.43%", "acres_equivalent": "~3.9 million acres"},
    uncertainty={"se": None, "ci95": None},
    n={"states": 12, "unit": "county-year panel, ~decade"}, design="observational panel (fixed effects, IV, long differences)",
    region="US Corn Belt (12 states)",
    source="Won S., Rejesus R.M., Goodwin B.K., Aglasan S. (2024) Understanding the effect of cover crop use on prevented planting losses. Am. J. Agric. Econ. 106(2):659-683",
    url="https://doi.org/10.1111/ajae.12396", doi="10.1111/ajae.12396",
    summary="More county cover-crop adoption is linked to lower prevented-planting losses, and the effect grows with multi-year use.",
    applicability="County-scale national insurance outcome (USD) for excess-WET springs (prevented planting), not a drought or field yield effect; web_key deliberately null. Use only as policy context.",
    use_as_prior=False, verification="secondary")

# ----------------------------------------------------------------------------------------------- E2 tillage
add(prior_id="E2_yield_pittelkow_fcr", strategy_id="E2", variant="no_till", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -7.6, "unit": "% change maize yield, no-till vs conventional tillage"},
    uncertainty={"se": None, "ci95": None, "note": "all-conditions maize value; maize in humid climates did not recover to CT yields after 3-10 yr"},
    n={"studies": 678, "paired_observations": 6005}, design="global meta-analysis",
    region="Global", source="Pittelkow C.M. et al. (2015) When does no-till yield more? A global meta-analysis. Field Crops Research 183:156-168",
    url="https://doi.org/10.1016/j.fcr.2015.07.020", doi="10.1016/j.fcr.2015.07.020",
    summary="No-till cut maize yields about 7.6% on average, and humid-climate maize did not catch up over time.",
    applicability="Central Iowa is humid, so a maize penalty is plausible. Overall no-till penalty is -4% with N fertilizer and -12% without. Companion Nature paper (Pittelkow et al. 2015, Nature 517:365-368, doi:10.1038/nature13809; 5463 obs, 610 studies) says no-till reduces yields on average, with smaller losses when combined with residue retention and rotation. A '5.7%' overall figure could not be confirmed.",
    verification="abstract")

add(prior_id="E2_yield_alkaisi_ames_cs", strategy_id="E2", variant="no_till", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -14.0, "unit": "% change corn yield, NT vs chisel plow, corn-soybean, Ames",
            "nt_vs_moldboard_pct": -15.4, "strip_till_vs_chisel_pct": -9.4,
            "yields_mg_ha": {"NT": 9.45, "ST": 9.96, "CP": 10.99, "DR": 10.90, "MP": 11.17}},
    uncertainty={"se": None, "ci95": None, "note": "NT significantly lower than CP/DR/MP at P<0.05; ST not different from NT or CP"},
    n={"site_years": "Ames 2003-2013 (corn years), 4 reps"}, design="long-term randomized split-plot experiment (7 Iowa locations)",
    region="central Iowa (Ames; Clarion-Nicollet-Webster soils)", derived=True,
    derivation="ratio of Table 4 mean yields (NT/CP - 1)",
    source="Al-Kaisi M.M., Archontoulis S.V., Kwaw-Mensah D., Miguez F. (2015) Tillage and crop rotation effects on corn agronomic response and economic return at seven Iowa locations. Agron. J. 107:1411-1424",
    url="https://mssoy.org/sites/default/files/documents/al-kaisi-et-al-agron-j-107-2015.pdf", doi="10.2134/agronj14.0470",
    summary="At Ames, no-till corn in corn-soy yielded about 14% below chisel plow; strip-till sat in between.",
    applicability="Best local prior for the E2 (web S2) corn-phase yield cost on poorly drained central Iowa soils. Penalty is smaller on well-drained southern Iowa soils. Across all sites, conventional tillage gave 11% more corn than NT in corn-corn-soy.",
    verification="full_text")

add(prior_id="E2_soil_loss_mhazo2016", strategy_id="E2", variant="no_till", outcome="soil_loss_pct", web_key="erosion_t_ac",
    effect={"mean": -60.0, "unit": "% change soil loss (water erosion), NT vs CT", "sediment_conc_pct": -56.0,
            "steep_slope_soil_loss_pct": -77.0, "long_plot_soil_loss_pct": -94.0},
    uncertainty={"se": None, "ci95": None}, n={"studies": 41, "paired_plots": 282}, design="global meta-analysis of runoff plots",
    region="Global", source="Mhazo N., Chivenge P., Chaplot V. (2016) Tillage impact on soil erosion by water: Discrepancies due to climate and soil characteristics. Agric. Ecosyst. Environ. 230:231-241",
    url="https://repo.mel.cgiar.org/items/7258ea0a-3450-402f-9faf-6076d226a136", doi="10.1016/j.agee.2016.04.033",
    summary="No-till cut water-erosion soil loss about 60% across 282 paired plots, more on steep slopes and long plots.",
    applicability="Water-erosion term of erosion_index. Runoff is unchanged on average, but about 40% lower in cool climates and trials longer than 5 years.",
    web_unit_compatible=False, conversion="relative change: erosion_t_ac_treated = phase2 baseline erosion_t_ac x (1 + mean/100)",
    verification="abstract")

add(prior_id="E2_sediment_prasad2023", strategy_id="E2", variant="no_till", outcome="sediment_pct", web_key="erosion_t_ac",
    effect={"mean": -86.0, "unit": "% change sediment loss, no-till with residue vs tillage (upper estimate, 'up to')",
            "runoff_depth_median_pct": 70.0},
    uncertainty={"se": None, "ci95": None, "note": "'up to 86%'; runoff depth medians were HIGHER under NT (+70 to +84%)"},
    n={"studies": 60, "site_years": 1575}, design="meta-analysis (US & Canada, 1968-2019)",
    region="US & Canada", source="Prasad L.R., Thompson A.M., Arriaga F.J., Koropeckyj-Cox L., Yuan Y. (2023) Effectiveness of residue and tillage management on runoff pollutant reduction from agricultural areas. J. ASABE 66(6):1341-1354",
    url="https://www.osti.gov/biblio/2425652", doi="10.13031/ja.15518",
    summary="In North American studies, no-till with residue cut sediment loss by up to 86%, but runoff volume and dissolved nutrients rose.",
    applicability="Upper-bound sediment prior for the region ('up to'). Keeping more than 30% residue cover reduced most runoff constituents.",
    web_unit_compatible=False, conversion="relative change (upper bound): erosion_t_ac_treated = phase2 baseline erosion_t_ac x (1 + mean/100); prefer Mhazo -60% as central value",
    verification="abstract")

add(prior_id="E2_tillage_erosion_mechanism_thaler2021", strategy_id="E2", variant="no_till", outcome="a_horizon_loss_area_pct", web_key=None,
    effect={"mean": 35.0, "unit": "% of cultivated Corn Belt area that has lost its A horizon (status, not a treatment effect)",
            "yield_reduction_pct": 6.0, "carbon_removed_pg": 1.4},
    uncertainty={"se": 11.0, "ci95": None, "note": "35 +/- 11%"},
    n={"region": "Corn Belt, remote sensing"}, design="observational (remote sensing + soil validation)",
    region="US Corn Belt", source="Thaler E.A., Larsen I.J., Yu Q. (2021) The extent of soil loss across the US Corn Belt. PNAS 118(8):e1922375118",
    url="https://pubmed.ncbi.nlm.nih.gov/33593895/", doi="10.1073/pnas.1922375118",
    summary="About a third of Corn Belt cropland has lost its A horizon, mostly on convex hilltops. This points to tillage erosion, which US erosion models do not simulate.",
    applicability="Justifies the curvature x tillage-intensity term in erosion_index; not an effect-size prior.",
    use_as_prior=False, verification="abstract")

add(prior_id="E2_tillage_translocation_lindstrom1992", strategy_id="E2", variant="no_till", outcome="tillage_translocation_t_ha_yr", web_key="erosion_t_ac",
    effect={"mean": 30.0, "unit": "t/ha/yr net soil loss from convex positions under moldboard plowing (upper value, simulated)"},
    uncertainty={"se": None, "ci95": None, "note": "'up to 30'; simulation over two hillslope landscapes, 100 years of alternating-direction plowing"},
    n={"landscapes": 2}, design="simulation calibrated to measured tillage translocation",
    region="US Upper Midwest (Minnesota) hillslopes",
    source="Lindstrom M.J., Nelson W.W., Schumacher T.E. (1992) Quantifying tillage erosion rates due to moldboard plowing. Soil & Tillage Research 24(3):243-255",
    url="https://scilit.com/publications/0ab87273840b0663b38667c4208a5456", doi="10.1016/0167-1987(92)90090-x",
    summary="Moldboard plowing can strip up to ~30 t/ha/yr off convex knolls; no-till sets this term near zero.",
    applicability="Use to scale the tillage-erosion term (convex curvature x tillage intensity). An absolute magnitude under moldboard plowing (no-till sets it near zero), not a % treatment effect. Value taken from a bibliographic record, not the paper.",
    web_unit_compatible=False, conversion="absolute: t/ha/yr x 0.4461 = short t/ac/yr (30 t/ha/yr = 13.4 short t/ac/yr upper value on convex knolls)",
    verification="secondary")

add(prior_id="E2_infiltration_basche2019", strategy_id="E2", variant="no_till", outcome="infiltration_pct", web_key=None,
    effect={"mean": 5.7, "unit": "% change infiltration, NT vs CT (not significant)", "precip_600_1000mm_pct": 55.6},
    uncertainty={"se": 9.7, "ci95": [-13.3, 24.7], "note": "SE from paper; CI derived as mean +/- 1.96*SE. 600-1000 mm/yr subset CI 5.8 to 105.3 (as reported)"},
    derived=True, derivation="ci95 = mean +/- 1.96*SE",
    n={"studies": 52, "paired_comparisons": 207}, design="global meta-analysis",
    region="Global", source="Basche & DeLonge (2019) PLoS ONE 14(9):e0215702", url="https://pmc.ncbi.nlm.nih.gov/articles/PMC6752860/",
    doi="10.1371/journal.pone.0215702",
    summary="Overall, no-till did not significantly change infiltration. In climates with 600-1000 mm rainfall (central Iowa gets ~900 mm), it raised infiltration by ~56%.",
    applicability="Central Iowa precipitation falls in the 600-1000 mm bin.", verification="full_text")

add(prior_id="E2_soc_ogle2019", strategy_id="E2", variant="no_till", outcome="soc_t_c_ha_yr", web_key=None,
    effect={"mean": 0.27, "unit": "t C/ha/yr (20-yr average), NT minus full tillage, cool moist climate, loamy/silty/clayey soils"},
    uncertainty={"se": None, "ci95": [0.00, 0.56]}, n={"sites": 178, "observations": 1205}, design="global meta-analysis with depth/mass-equivalent correction",
    region="Global; cool temperate moist class (central Iowa MAT ~9-10 C)",
    source="Ogle S.M. et al. (2019) Climate and soil characteristics determine where no-till management can store carbon in soils and mitigate greenhouse gas emissions. Scientific Reports 9:11665",
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC6691111/", doi="10.1038/s41598-019-47861-7",
    summary="In cool moist climates on loamy to clayey soils, no-till stores only ~0.27 t C/ha/yr more over 20 years, with a CI touching zero.",
    applicability="Central Iowa sits at the cool/warm boundary (warm moist: 0.33, CI 0.03-0.61). No-till has more SOC above ~20 cm and full tillage more below.",
    verification="full_text", notes="DOI verified via Crossref.")

# ----------------------------------------------------------------------------------------------- E3 prairie strips
SCH = dict(n={"catchments": 12, "design_detail": "randomized balanced incomplete block; 3 reps x 4 treatments (0, 10% footslope, 10% strips, 20% strips)",
              "years": "2007-2013 (water 2008-2013)"},
           design="randomized catchment-scale experiment (STRIPS)",
           region="Neal Smith National Wildlife Refuge, Jasper County, Iowa (inside HLS tile 15TVG); no-till corn-soybean",
           source="Schulte L.A., Niemi J., Helmers M.J., Liebman M., Arbuckle J.G., James D.E., Kolka R.K., O'Neal M.E., Tomer M.D., Tyndall J.C., et al. (2017) Prairie strips improve biodiversity and the delivery of multiple ecosystem services from corn-soybean croplands. PNAS 114(42):11247-11252",
           url="https://www.fs.usda.gov/nrs/pubs/jrnl/2017/nrs_2017_schulte_001.pdf", doi="10.1073/pnas.1620229114",
           verification="full_text", derived=True, derivation="percent = (1/fold - 1)*100 for point and CI bounds (fold-change CIs from paper)")
add(prior_id="E3_sediment_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="sediment_pct", web_key="erosion_t_ac",
    effect={"mean": fold_to_pct(20), "unit": "% change sediment export in surface runoff (paper: 20-fold lower)"},
    uncertainty={"se": None, "ci95": [fold_to_pct(5.6), fold_to_pct(50)], "fold_ci95": [5.6, 50]},
    summary="Prairie strips cut sediment export about 20-fold (~95%) versus all-crop catchments.",
    applicability="Same tile as COUNTERFIELD; the baseline catchments were already no-till. Fully cropped controls lost 13 Mg/ha/yr of soil. No web card for prairie strips (web_strategy_id null).",
    web_unit_compatible=False, conversion="relative change: erosion_t_ac_treated = phase2 baseline erosion_t_ac x (1 + mean/100)", **SCH)
add(prior_id="E3_tp_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="total_p_runoff_pct", web_key=None,
    effect={"mean": fold_to_pct(4.3), "unit": "% change total P in surface runoff (paper: 4.3x lower)"},
    uncertainty={"se": None, "ci95": [fold_to_pct(1.4), fold_to_pct(14)], "fold_ci95": [1.4, 14]},
    summary="Total phosphorus loss fell about 77%.", applicability="Same tile.", **SCH)
add(prior_id="E3_tn_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="total_n_runoff_pct", web_key=None,
    effect={"mean": fold_to_pct(3.3), "unit": "% change total N in surface water (paper: 3.3x lower)"},
    uncertainty={"se": None, "ci95": [fold_to_pct(12), fold_to_pct(0.9)], "fold_ci95": [0.9, 12], "note": "CI includes no effect"},
    summary="Total nitrogen in surface water fell about 70%, but the CI includes zero.",
    applicability="Same tile. Total N in surface runoff, not nitrate, so web_key is null; for nitrate_pct use E3_no3_gw_schulte2017 (groundwater NO3-N).", **SCH)
add(prior_id="E3_no3_gw_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="nitrate_conc_pct", web_key="nitrate_pct",
    effect={"mean": fold_to_pct(3.6), "unit": "% change groundwater NO3-N concentration (paper: 3.6x lower)"},
    uncertainty={"se": None, "ci95": [fold_to_pct(13), fold_to_pct(1.0)], "fold_ci95": [1.0, 13]},
    summary="Shallow-groundwater nitrate concentrations were about 72% lower.", applicability="Same tile; small catchments without tile drainage.", **SCH)
add(prior_id="E3_runoff_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="runoff_pct", web_key=None,
    effect={"mean": -37.0, "unit": "% change total water runoff (abstract: 37%; results: 1.6x less)"},
    uncertainty={"se": None, "ci95": [fold_to_pct(2.3), fold_to_pct(1.1)], "fold_ci95": [1.1, 2.3]},
    summary="Total runoff dropped about 37%.", applicability="Same tile.", **SCH)
add(prior_id="E3_yield_schulte2017", strategy_id="E3", variant="10pct_strips", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 0.0, "unit": "% change corn/soy yield on the remaining cropped area", "land_taken_out_pct": 10.0,
            "whole_field_yield_change": "reduced roughly in proportion to area converted (~-10%)"},
    uncertainty={"se": None, "ci95": None, "note": "no detectable difference on cropped portion"},
    summary="Yield per cropped acre was unchanged. Whole-catchment production fell only by the share of land taken out.",
    applicability="For the card: yield_pct on the remaining area is about 0, and production per field is about -10% at 10% strips. Extension summaries (Helmers 2012 data) give 95% sediment, ~85-90% N and ~89-90% P reductions in surface runoff.",
    **{k: v for k, v in SCH.items() if k not in ("derived", "derivation")})

# ----------------------------------------------------------------------------------------------- E4 extended rotation
MAR = dict(n={"blocks": 4, "years": "2003-2011", "obs_per_system": 36},
           design="long-term randomized complete block experiment (Marsden Farm)",
           region="Boone, Iowa (ISU Marsden Farm; inside HLS tile 15TVG)",
           source="Davis A.S., Hill J.D., Chase C.A., Johanns A.M., Liebman M. (2012) Increasing cropping system diversity balances productivity, profitability and environmental health. PLoS ONE 7(10):e47149",
           url="https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0047149", doi="10.1371/journal.pone.0047149",
           verification="full_text")
add(prior_id="E4_corn_yield_davis2012", strategy_id="E4", variant="3yr_4yr", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 4.0, "unit": "% change maize yield vs 2-yr corn-soy", "mg_ha": {"2yr": 12.3, "3yr": 12.7, "4yr": 12.9}},
    uncertainty={"se": None, "ci95": None, "sem_mg_ha": {"2yr": 0.1, "3yr": 0.2, "4yr": 0.2}, "p": 0.03},
    summary="Maize averaged 4% higher in the 3- and 4-year rotations than in corn-soy, despite far less N and herbicide.",
    applicability="Same tile. The diverse systems received manure.", **MAR)
add(prior_id="E4_soy_yield_davis2012", strategy_id="E4", variant="3yr_4yr", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 9.0, "unit": "% change soybean yield vs 2-yr", "mg_ha": {"2yr": 3.4, "3yr": 3.8, "4yr": 3.8}},
    uncertainty={"se": None, "ci95": None, "sem_mg_ha": {"2yr": 0.07, "3yr": 0.08, "4yr": 0.08}, "p": 0.01},
    summary="Soybean averaged 9% higher in the diverse rotations.", applicability="Same tile.", **MAR)
add(prior_id="E4_nfert_davis2012", strategy_id="E4", variant="3yr_4yr", outcome="n_fert_pct", web_key=None,
    effect={"mean": -83.0, "unit": "% change manufactured N fertilizer rate (rotation-average kg N/ha)", "kg_n_ha": {"2yr": 80, "3yr": 16, "4yr": 11}},
    uncertainty={"se": None, "ci95": None, "sem_kg": {"2yr": 3, "3yr": 3, "4yr": 2}},
    derived=True, derivation="mean of (16/80-1) and (11/80-1) = -80% and -86%",
    summary="Manufactured N use fell 80-86%.", applicability="Same tile; manure supplied part of the N.",
    **{k: v for k, v in MAR.items()})
add(prior_id="E4_herbicide_davis2012", strategy_id="E4", variant="3yr_4yr", outcome="herbicide_pct", web_key=None,
    effect={"mean": -88.0, "unit": "% change herbicide input, 3-yr and 4-yr vs 2-yr rotation (paper: 'reducing herbicide use by 88%')",
            "range": [-90.0, -83.3], "range_note": "implied by the abstract's '6 to 10 times lower' (spread between 3-yr and 4-yr systems), not a CI; derived as (1/6-1) and (1/10-1)",
            "freshwater_toxicity": "~200x lower"},
    uncertainty={"se": None, "ci95": None, "note": "no CI reported; see effect.range for the 6-10x spread"},
    summary="Herbicide use was 88% lower (6-10 times lower) with equal weed control.",
    applicability="Same tile.", **{k: v for k, v in MAR.items()})
add(prior_id="E4_drought_bowles2020", strategy_id="E4", variant="diverse_rotation", outcome="drought_yield_loss_reduction_pct", web_key="drought_loss_pct",
    effect={"mean": None, "unit": "% reduction in maize drought-year yield loss (range across sites with credible effects)", "range": [14.0, 89.9],
            "maize_yield_all_conditions_pct": 28.1, "maize_yield_favorable_pct": 22.6},
    uncertainty={"se": None, "ci95": None, "note": "range across sites, not a CI. The 28.1% average covers only sites with credible effects and compares most-diverse vs simplest rotation (often monoculture)"},
    n={"sites": 11, "region": "US & Canada long-term experiments"}, design="multilevel analysis of long-term rotation experiments",
    region="North America (11 sites; no Iowa site; Minnesota C-S vs C-S-O/A-A not significant in drought years)",
    source="Bowles T.M. et al. (2020) Long-term evidence shows that crop-rotation diversification increases agricultural resilience to adverse growing conditions in North America. One Earth 2(3):284-293",
    url="https://par.nsf.gov/servlets/purl/10331499", doi="10.1016/j.oneear.2020.02.007",
    summary="More diverse rotations raised maize yields and cut drought-year losses by 14-90% across sites with credible effects.",
    applicability="Treat as an upper bound against a corn-soy baseline. The closest analog (MN, vs C-S) showed no significant drought benefit. Pair with Kluger et al. 2025 (diversification beyond corn-soy: -3.4% for US corn). Range only, no central value, so use_as_prior=false: there is NO numeric trial prior for drought_loss_pct.",
    prior_kind="range", use_as_prior=False, web_unit_compatible=False,
    conversion="relative reduction of drought-year loss: drought_loss_pct_treated = baseline drought_loss_pct x (1 - r/100), r in effect.range; range only, use for plausibility bounds",
    verification="full_text")
add(prior_id="E4_corn_divers_kluger2025", strategy_id="E4", variant="diverse_rotation", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": -3.4, "unit": "% of mean US corn yield: diversified (3-yr) vs simple S->C rotation (net effect)"},
    uncertainty={"se": None, "ci95": None, "note": "statistically significant (alpha=0.05); CI in Fig. 5 only"},
    n={"treated": 811541, "control": 432622, "note": "sample sizes of the S->C vs C->C precrop analysis"},
    design="observational (satellite yield proxy + causal forest)", region="United States",
    source="Kluger D.M., Di Tommaso S., Lobell D.B. (2025) Precrop payoffs: causal machine learning reveals large but variable yield benefits of crop rotation in major breadbaskets. Environ. Res. Lett. 20(11):114037",
    url="https://arxiv.org/html/2506.02384v2", doi="10.1088/1748-9326/ae0f45",
    summary="For US corn, adding a third crop beyond the corn-soy alternation was associated with ~3% lower corn yield (net of input changes).",
    applicability="Shown next to Bowles 2020 per the design doc. Observational; mostly small grains, not oat/clover.",
    use_as_prior=False, verification="full_text")

# ----------------------------------------------------------------------------------------------- E5 rotation benefit
add(prior_id="E5_corn_kluger2022", strategy_id="E5", variant="cs_vs_cc", outcome="yield_t_ha", web_key=None,
    effect={"mean": 1.03, "unit": "t/ha corn rotation benefit (soy precrop vs corn precrop), whole dataset", "coolest_quintile": 1.19, "hottest_quintile": 0.85,
            "soy_benefit_t_ha": 0.21, "soy_cool": 0.16, "soy_hot": 0.24},
    uncertainty={"se": None, "ci95": None},
    n={"design_note": "randomized rotation trials combined with satellite observational data"},
    design="trial + satellite hybrid (randomized experiments anchoring observational estimates)",
    region="US Midwest", source="Kluger D.M., Owen A.B., Lobell D.B. (2022) Combining randomized field experiments with observational satellite data to assess the benefits of crop rotations on yields. Environ. Res. Lett. 17(4):044066",
    url="https://doi.org/10.1088/1748-9326/ac6083", doi="10.1088/1748-9326/ac6083",
    web_key_after_conversion="yield_pct",
    web_unit_compatible=False, conversion="absolute t/ha: yield_pct = 100 x mean / local continuous-corn yield (t/ha); phase2 converts with NASS county corn yield (bu/ac x 0.06277 = t/ha). web_key null until converted",
    summary="Corn after soybean yielded ~1.0 t/ha more than corn after corn. The benefit shrinks in hot conditions; the soybean benefit grows with heat.",
    applicability="This is the PRIMARY design anchor for COUNTERFIELD's trial+satellite hybrid. The heat interaction matters for the 2045 transport.",
    verification="abstract", notes="Numbers from the published ERL 17(4):044066 abstract (Crossref metadata): corn 0.85 / 1.03 / 1.19 t/ha for top temperature quintile / whole dataset / bottom quintile; soybean 0.24 / 0.21 / 0.16. (arXiv v1 had 0.84 / 1.02 / 1.18 and 0.20.)")
add(prior_id="E5_corn_kluger2025", strategy_id="E5", variant="cs_vs_cc", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 2.5, "unit": "% of mean US corn yield, S->C vs C->C (net effect)", "us_soy_C_to_S_vs_S_to_S_pct": 8.5,
            "median_across_36_combinations_pct": 4.5},
    uncertainty={"se": None, "ci95": None, "note": "both significant at alpha=0.05; HC3 CIs shown in Fig. 3"},
    n={"treated": 811541, "control": 432622}, design="observational (satellite + causal forest)", region="United States",
    source="Kluger, Di Tommaso & Lobell (2025) Environ. Res. Lett. 20(11):114037", url="https://arxiv.org/html/2506.02384v2",
    doi="10.1088/1748-9326/ae0f45",
    summary="Net rotation benefit for US corn was ~2.5% and for US soybean ~8.5%.",
    applicability="Already rotation-vs-CC direction (benefit expressed as % of mean US corn yield, not of CC yield). Net of reduced N in rotated corn, so it is smaller than trial (direct) effects.", use_as_prior=False, verification="full_text")
add(prior_id="E5_corn_seifert2017", strategy_id="E5", variant="cs_vs_cc", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 4.5, "unit": "% change corn yield, rotated vs continuous corn (rotation benefit relative to CC yield)",
            "reported": {"cc_penalty_pct_of_rotated_yield": 4.3, "mg_ha": 0.42, "bu_ac": 6.7, "continuous_soy_penalty_pct": 10.3}},
    uncertainty={"se": None, "ci95": None},
    n={"yield_records": 748374, "years": "2007-2012", "states": 6}, design="observational (RMA field yields + CDL rotations, regression)",
    region="US Midwest incl. Iowa", source="Seifert C.A., Roberts M.J., Lobell D.B. (2017) Continuous corn and soybean yield penalties across hundreds of thousands of fields. Agron. J. 109:541-548",
    url="https://mssoy.org/sites/default/files/documents/seifert-et-al-agron-j-109-2017.pdf", doi="10.2134/agronj2016.03.0134",
    summary="Across ~750k field records, continuous corn yielded 4.3% less and continuous soybean 10.3% less than rotated crops.",
    applicability="Penalty is larger in low-moisture, low-yield places and grows up to 3 consecutive years.",
    derived=True, derivation="benefit = 1/(1 - penalty) - 1 = 1/(1-0.043) - 1 = +4.5%",
    use_as_prior=False, verification="full_text", notes="DOI verified via Crossref.")
add(prior_id="E5_corn_alkaisi2015", strategy_id="E5", variant="cs_vs_cc", outcome="yield_pct", web_key="yield_pct",
    effect={"mean": 18.5, "unit": "% change corn yield, corn-soy rotation vs continuous corn at Ames (rotation benefit relative to CC yield)",
            "range": [12.4, 38.9], "range_note": "site range across 7 Iowa sites, converted from the reported CC penalty range; not a CI",
            "reported": {"cc_penalty_pct_range": [11.0, 28.0], "ames_table4_mg_ha": {"CS": 10.49, "CCS": 9.63, "CC": 8.85},
                         "ames_cc_vs_cs_pct_from_table4": -15.6}},
    uncertainty={"se": None, "ci95": None, "note": "no CI. Ames value from Table 4 means over all years/tillage (not the same-year Fig. 5 comparison)"},
    n={"sites": 7, "years": "2003-2013", "reps": 4}, design="long-term randomized split-plot experiment",
    region="Iowa (7 ISU farms; Ames = central Iowa)", derived=True,
    derivation="Ames: 10.49/8.85 - 1 = +18.5%; range: 1/(1-0.11) - 1 = +12.4% to 1/(1-0.28) - 1 = +38.9%",
    source="Al-Kaisi et al. (2015) Agron. J. 107:1411-1424", url="https://mssoy.org/sites/default/files/documents/al-kaisi-et-al-agron-j-107-2015.pdf",
    doi="10.2134/agronj14.0470",
    summary="In Iowa trials, continuous corn yielded 11-28% less than rotated corn depending on site, even with higher N (rotation benefit +12% to +39% of CC yield; Ames +18.5%).",
    applicability="Direct (trial) effect at fixed recommended N; larger than net observational estimates.", verification="full_text")

# ----------------------------------------------------------------------------------------------- citation checks
CITATION_CHECKS = [
    {"claim": "PCCP 2021 enrolled '12.2 million acres' (design doc: '12.2M acres vs 5M forecast')",
     "verdict": "partly",
     "corrected_statement": "About 12.2 million net acres received the $5/acre premium reduction under the 2021 Pandemic Cover Crop Program (FCIC/RMA final rule establishing the 2022 PCCP). American Farmland Trust's analysis of RMA Summary of Business data gives a total 2021 cost of $59.4 million. No source was found for a '5 million acre forecast'; drop that comparison or cite it separately.",
     "source_url": "https://rma.usda.gov/sites/default/files/about/2022-02965.pdf",
     "supporting_urls": ["https://farmland.org/what-state-received-the-most-pandemic-cover-crop-program-funding/",
                         "https://www.rma.usda.gov/policy-procedure/bulletins-memos/managers-bulletin/2021/mgr-21-003-covid-19-pandemic-cover-crop"],
     "evidence": "Rule text, Cost Benefit Analysis Summary: 'Approximately 12.2 million net acres have received a premium reduction for the crop year 2021 PCCP'. The same rule projects 23 million eligible acres and $116.2M for 2022.",
     "verification": "full_text"},
    {"claim": "Kluger, Di Tommaso & Lobell 2025 'Precrop Payoffs': journal/volume/article id; 'median precrop benefit 4.5%'",
     "verdict": "verified",
     "corrected_statement": "Kluger D.M., Di Tommaso S., Lobell D.B. (2025). Precrop payoffs: causal machine learning reveals large but variable yield benefits of crop rotation in major breadbaskets. Environmental Research Letters 20(11): 114037 (published online 17 Oct 2025). doi:10.1088/1748-9326/ae0f45. The paper reports a median estimated NET rotation benefit of 4.5% on yield across all 36 precrop x outcome-crop x country combinations (US, Canada, France, China). It is not a US corn-soy figure: US soybean->corn = +2.5%, US corn->soybean = +8.5% (Table S9).",
     "source_url": "https://doi.org/10.1088/1748-9326/ae0f45",
     "supporting_urls": ["https://api.crossref.org/works/10.1088/1748-9326/ae0f45", "https://arxiv.org/html/2506.02384v2"],
     "evidence": "Crossref metadata (volume 20, issue 11, article 114037). The 4.5% median sentence appears in the Discussion of arXiv v2 (Oct 2025), which corresponds to the accepted version.",
     "verification": "full_text (arXiv v2) + Crossref metadata"},
    {"claim": "Won et al. 2024 AJAE: '$40M per 1 percent' cover crop adoption reduction in prevented-planting losses",
     "verdict": "partly",
     "corrected_statement": "Won S., Rejesus R.M., Goodwin B.K., Aglasan S. (2024) Am. J. Agric. Econ. 106(2):659-683 (online Feb 2023), doi:10.1111/ajae.12396. Using 2019 values, a ONE-PERCENTAGE-POINT increase in cover crop adoption (~3.9 million acres nationally) is estimated to lower the prevented-planting loss ratio from 4.47% to 4.43%. With $96.73B liabilities, that is about $38.69 million less in prevented-planting indemnities for 2019. 'Nearly $40 million per 1%' is press-release wording (NC State). It is a percentage-point change and a one-year (2019) counterfactual, not an annual recurring saving.",
     "source_url": "https://doi.org/10.1111/ajae.12396",
     "supporting_urls": ["https://news.ncsu.edu/?p=544964", "https://econpapers.repec.org/RePEc:wly:ajagec:v:106:y:2024:i:2:p:659-683"],
     "evidence": "Publisher full text was blocked (HTTP 403) from this environment. The percentage-point wording and the $38.69M / 4.47->4.43% / 3.9M-acre figures come from a search-engine extraction of the Wiley article page. The press release says '1% increase ... nearly $40 million'.",
     "verification": "secondary (re-check the paper's Section on economic significance before printing)"},
]


def shock_years():
    summ_p = os.path.join(USDM_DIR, "usdm_tile_weekly.csv")
    if not os.path.exists(summ_p):
        subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", "evidence_usdm.py")], check=True)
    df = pd.read_csv(summ_p, parse_dates=["date"])
    core = ["Story", "Boone", "Polk", "Marshall", "Hamilton", "Hardin", "Jasper", "Dallas"]
    c = df[df.county.isin(core)].copy()
    c["month"] = c.date.dt.month
    monthly = c.groupby([c.date.dt.year.rename("year"), "month"])[["d0", "d1", "d2", "d3"]].mean().round(1)

    def yr(y):
        m = monthly.loc[y]
        gs = m.loc[5:9]
        return {"year": int(y),
                "usdm_core_counties_monthly_mean_pct_area": {
                    int(k): {"D0+": float(v.d0), "D1+": float(v.d1), "D2+": float(v.d2), "D3+": float(v.d3)} for k, v in m.iterrows()},
                "may_sep_mean_D1plus_pct": round(float(gs.d1.mean()), 1),
                "may_sep_mean_D2plus_pct": round(float(gs.d2.mean()), 1),
                "may_sep_max_month_D2plus_pct": round(float(gs.d2.max()), 1)}

    usdm_src = {"name": "US Drought Monitor county statistics (categorical cumulative % area; 8 core tile counties averaged)",
                "url": "https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent?aoi=19169&startdate=1/1/2016&enddate=12/31/2024&statisticsType=1",
                "raw_cache": "data/raw/usdm/usdm_tile_weekly.csv"}
    by_year = {y: yr(y) for y in range(2016, 2025)}
    return {
        "method": "Drought classification from USDM weekly county statistics for Story, Boone, Polk, Marshall, Hamilton, Hardin, Jasper, Dallas (pipeline/evidence_usdm.py). Growing season = May-Sep. D1+ = moderate drought or worse.",
        "source": usdm_src,
        "events": [
            {"year": 2020, "type": "derecho (wind) + late-season drought", "treat_as_shock": True,
             "date": "2020-08-10",
             "detail": "Derecho crossed central Iowa late morning to early afternoon of 10 Aug 2020 (a seismometer near Des Moines recorded the winds ~10:26-12:08 local). The official peak in the NWS Des Moines area was 99 mph at Marshalltown ASOS. Storm reports came from Story (Ames, Nevada), Polk, Marshall, Boone, Jasper, Dallas, Hardin and Tama counties, with flattened corn and defoliated soybeans. NOAA NCEI lists the event at $11.0B (Historic Midwest Derecho). Drought (USDM D1+) also developed Jul-Oct 2020: core-county D1+ 79% Aug, 95% Sep; D2+ 46-52%.",
             "sources": [{"name": "NWS Des Moines, August 10, 2020 Derecho event page", "url": "https://www.weather.gov/dmx/2020derecho"},
                         {"name": "NOAA NCEI / Climate.gov 2020 billion-dollar disasters", "url": "https://www.climate.gov/disasters2020"},
                         usdm_src],
             "usdm": by_year[2020]},
            {"year": 2021, "type": "growing-season drought", "treat_as_shock": True,
             "detail": "Strongest in-season drought of 2016-2024 in the tile counties: D1+ 93-97% of area Jun-Sep, D2+ 48-59% Jun-Aug, D3 ~14% in Aug. Not in the design's hindcast window, but must be flagged as a drought year (Iowa still posted high yields in 2021, so drought != yield loss).",
             "sources": [usdm_src], "usdm": by_year[2021]},
            {"year": 2022, "type": "late-season drought (Aug onward)", "treat_as_shock": True,
             "detail": "May-Jul 2022 had essentially no drought in the core counties (D1+ 0%). Drought developed in August (D1+ 38%, D2+ 6%), eased in September (D1+ 27%) and intensified in Oct-Dec (D1+ 73-100%). Iowa DNR water summaries describe drought worsening from late summer into fall, especially in central and east-central Iowa. Impact on 2022 grain fill is real but late; treat as a moderate, late-season shock.",
             "sources": [usdm_src, {"name": "Iowa DNR Water Summary Update, Oct 2022", "url": "https://publications.iowa.gov/51755/1/20221006wsu.pdf"}],
             "usdm": by_year[2022]},
            {"year": 2023, "type": "growing-season dryness escalating to drought late summer", "treat_as_shock": True,
             "detail": "Core counties were abnormally dry (D0) over ~100% of area Jun-Sep. D1+ was 13% (Jun), 29% (Jul), 34% (Aug), then 97% in Sep with D2+ 49%. NWS Des Moines reported much of central and west-central Iowa in D2 by September, with D3 expanding into central Iowa by December 2023.",
             "sources": [usdm_src, {"name": "NWS Des Moines Drought Information Statement, 28 Sep 2023", "url": "https://www.weather.gov/media/dmx/DGT/DGT_DMX_09282023.pdf"},
                         {"name": "NWS Des Moines Drought Information Statement, 21 Dec 2023", "url": "https://www.weather.gov/media/dmx/DGT/DGT_DMX_12212023.pdf"}],
             "usdm": by_year[2023]},
        ],
        "assessment_for_hindcast": "The region.json hindcast event ('2022-2023 Midwest drought') is supported, with a caveat. In the tile counties, 2022 drought began in August and 2023 drought (D1+) covered only 13-34% of the area until September. By USDM, 2021 was the most severe in-season drought year in the 2016-2024 panel and sits inside the training window (2016-2021). Phase 2 should define drought_flag from weather data (POWER/IMERG precipitation and heat, or these USDM values) instead of assuming whole-season drought in 2022-2023, and should either treat 2021 as a drought year in training or note it explicitly.",
        "by_year_all": by_year,
    }


def main():
    for p in P:
        finalize(p)
    for p in P:  # store every CI as [lower, upper]
        ci = p["uncertainty"].get("ci95")
        if ci:
            p["uncertainty"]["ci95"] = sorted(ci)
        fci = p["uncertainty"].get("fold_ci95")
        if fci:
            p["uncertainty"]["fold_ci95"] = sorted(fci)
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "module": "evidence",
        "description": ("Effect priors from randomized / long-term controlled trials and meta-analyses relevant to central Iowa corn-soy, "
                        "plus observational contrasts and context records (use_as_prior=false), citation checks and shock years. "
                        "Effects are % change of treatment vs control unless the unit says otherwise; negative = reduction. "
                        "For E5 the treatment is the corn-soy rotation and the control is continuous corn (benefit as % of CC yield). "
                        "Only priors with prior_kind='numeric' have a usable effect.mean; 'counts', 'range' and 'qualitative' records have mean=null and use_as_prior=false. "
                        "Strategy IDs E1..E5 are evidence IDs, NOT web card IDs: join to web/data/effects.json via web_strategy_id (or web_strategy_map), never on strategy_id. "
                        "web_unit_compatible=false means the value must be converted as described in `conversion` before it can fill the web_key outcome."),
        "web_strategy_map": WEB_STRATEGY_MAP,
        "strategies": STRATEGIES,
        "verification_levels": {"full_text": "number read in full text", "abstract": "number read in official abstract/landing page",
                                "secondary": "number from extension/press/search extraction; original not opened"},
        "priors": P,
        "citation_checks": CITATION_CHECKS,
        "shock_years": shock_years(),
    }
    # the diagnostic CSV written by evidence_usdm.py must use the same aggregation as shock_years
    core_csv = os.path.join(USDM_DIR, "usdm_core_by_year.csv")
    if os.path.exists(core_csv):
        cby = pd.read_csv(core_csv, index_col=0)
        for y, v in out["shock_years"]["by_year_all"].items():
            assert abs(cby.loc[int(y), "may_sep_mean_D1plus_pct"] - v["may_sep_mean_D1plus_pct"]) < 1e-9, y
            assert abs(cby.loc[int(y), "may_sep_mean_D2plus_pct"] - v["may_sep_mean_D2plus_pct"]) < 1e-9, y
    json.dump(out, open(OUT, "w"), indent=2)
    # sanity
    ids = [p["prior_id"] for p in P]
    assert len(ids) == len(set(ids)), "duplicate prior ids"
    for p in P:
        for k in ("strategy_id", "web_strategy_id", "prior_kind", "web_unit_compatible", "conversion", "outcome", "effect", "uncertainty", "n", "design", "region", "source", "url", "summary", "applicability", "verification"):
            assert k in p, (p["prior_id"], k)
    print(f"wrote {OUT}: {len(P)} priors, {len(CITATION_CHECKS)} citation checks")
    print(pd.Series([p["strategy_id"] for p in P]).value_counts().sort_index().to_string())
    print("use_as_prior true/false:", sum(p["use_as_prior"] for p in P), "/", sum(not p["use_as_prior"] for p in P))
    print("prior_kind:", pd.Series([p["prior_kind"] for p in P]).value_counts().to_dict())
    print("with DOI:", sum(bool(p.get("doi")) for p in P), "of", len(P), "; unique DOIs:", len({p["doi"] for p in P if p.get("doi")}))
    print("web_key counts (use_as_prior & numeric):",
          pd.Series([p["web_key"] for p in P if p["use_as_prior"] and p["web_key"]]).value_counts().to_dict())


if __name__ == "__main__":
    main()
