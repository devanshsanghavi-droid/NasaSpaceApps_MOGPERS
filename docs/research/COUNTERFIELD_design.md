# COUNTERFIELD (v2, red-team corrected)

**Pitch:** For any U.S. field, COUNTERFIELD shows what each rotation choice has actually done on real fields of the same type that already tried it. It says how sure that evidence is and whether it still holds in the field's 2045 climate. When the evidence is thin, it turns the farmer's own field into a randomized strip trial that makes the national evidence better for everyone.

**30-second story:** U.S. farmers run millions of unplanned rotation experiments every season, and NASA satellites record the outcomes. COUNTERFIELD turns that record into causal evidence for one specific field. It anchors the satellite estimates on randomized trials and on natural experiments created by government programs, and it closes the loop: each farmer it cannot yet advise confidently becomes a trial site.

---

## 1. Why this is not a lookup table

The question a farmer asks is causal: *"What would MY field do under a rotation it has never grown?"*

- Lookup tables (the Midwest Cover Crops Council selector, NRCS guides) answer "what usually grows here".
- Process models (Regrow/DNDC, Indigo/DayCent, CIBO/SALUS) answer "what does a simulator predict".
- Correlations, such as peer benchmarking at Farmers Business Network, are confounded: farmers who diversify differ in soil, drainage and skill.

COUNTERFIELD estimates **heterogeneous causal effects from observed outcomes**. It then corrects them in two ways:

- Against **randomized trials**: Practical Farmers of Iowa strip trials since 2009, the DIFM on-farm trials, USDA long-term research (LTAR) sites, and the Iowa State STRIPS prairie-strip experiments.
- Against **quasi-experiments**: changes in adoption caused by program rollouts rather than by the farmer.

## 2. Closest prior work, and what is genuinely new

| Prior work | What it already does | What COUNTERFIELD adds |
|---|---|---|
| Deines et al. 2023 (GCB) | Causal forest on about 90k fields. Cover crops *associated with* -5.5% maize / -3.5% soy | Turns a retrospective average into a prospective, per-field-type planner |
| Kluger, Owen & Lobell 2022 (ERL); Kluger, Di Tommaso & Lobell 2025 | Trial + satellite hybrid estimator for precrop effects. Satellite-only estimates do worse | Uses the hybrid as the **core** estimator, across several practices and outcomes, with climate transport |
| Giannarakis, Sitokonstantinou et al. 2022; Tsoumas et al. AAAI 2023 | Field-level double machine learning (DML) for sustainable practices; causal evaluation of an ag recommender | Adds U.S.-wide program instruments, randomized-trial anchoring and a value-of-information trial loop |
| Iowa State Daily Erosion Project | Rainfall-driven erosion modelling (WEPP model) at watershed scale | Consumes it as the erosion outcome and adds tillage erosion |
| ACPF (USDA ARS), Profit Zone Manager | Siting of conservation practices | Provides causal benefit estimates for each site |
| NASA Acres / NASA Harvest | Satellite layers for cover crops, tillage and soil carbon | Consumes these layers and builds the decision engine on top |

**The claimed contributions:**
1. **Quasi-experimental identification from program rollouts.** Iowa's cover-crop insurance discount (launched 2017), the national Pandemic Cover Crop Program (PCCP, 2021), and cost-share budget exhaustion are used as instruments or encouragement designs.
2. **Trial-anchored effects by field type** for every CONUS field, with coverage calibrated *after* any filtering of what gets shown.
3. **A value-of-information loop** that routes uncertain farmers into randomized strip trials. The tool becomes a national learning system: the more farmers use it, the stronger the evidence.
4. **NASA signposts** that keep monitoring the plan after it is delivered.
5. **Impact accounting attributable to the tool,** with no double counting.

---

## 3. Architecture

```
L0 FIELDS & TREATMENTS      Crop Sequence Boundaries (linked across editions) + CDL 2008-2024
                            HLS L30+S30 (2016-2025) -> unmix into green / residue / bare fractions
                            NDTI -> tillage intensity (enables a reduced/no-till regime)
                            Treatment = intent-to-treat at FIRST adoption (non-absorbing)
        |
L1 HARMONIZE (field = unit) Confounders: SSURGO/gNATSGO, SRTM/3DEP terrain, NASA POWER/NLDAS weather,
                            Prithvi-EO-2.0 embeddings of pre-period HLS. Regional modifiers only:
                            SMAP L4 (9 km), GRACE-FO (~300 km). Field moisture proxy: Sentinel-1 SAR
                            + ECOSTRESS/OpenET ET
        |
L2 OUTCOMES (measured)      Yield: HLS yield model calibrated to NASS county yields
                            Water: OpenET 30 m ET + ECOSTRESS ET/ESI/LST   -> water productivity
                            Erosion: Daily Erosion Project WEPP + tillage translocation (curvature x NDTI)
                            Resilience: yield anomaly in drought / excess-wet years
   SIDECAR (modelled, striped)  N2O, nitrate, soil-carbon magnitude from meta-analysis priors / KGML emulator
        |
L3 CAUSAL CORE              PRIMARY (pre-registered): trial + satellite hybrid (Kluger) on field types
                            Quasi-experiments: IV / encouragement from program rollouts and budget shocks
                            Diagnostics: non-absorbing staggered DiD (de Chaisemartin-D'Haultfoeuille),
                            causal forest / DR-learner, negative controls, spatial-block cross-fitting
        |
L4 UNCERTAINTY              Badges calibrated on a semi-synthetic benchmark with spatially structured
                            hidden confounders; conformal coverage audited after selection;
                            sensitivity Gamma (correctly defined); overlap / evidence count
        |
L5 CLIMATE TRANSPORT        NEX-GDDP-CMIP6 (multi-model, SSP2-4.5 / 5-8.5) effect-modifier distributions;
                            out-of-support -> CONUS climate-analog field types -> else "beyond evidence"
        |
L6 DECISION                 Pairwise preference cards (BOPE) -> utility + risk dial -> Pareto set (current + >=3)
                            PRIM failure boxes -> adaptation pathways with NASA signposts
                            Value of information -> "run THIS strip trial" -> results feed back into L3
                            Landscape: policy trees for EQIP/CSP targeting, scored by doubly-robust policy value
        |
L7 DELIVERY                 Map + field-type twins + strategy cards + season ribbon; voice/SMS where numbers
                            come only from tool calls; agronomist review queue for thin evidence
        ^_______________ each season: new HLS / SMAP / ECOSTRESS + strip-trial results __________|
```

### How each NASA dataset is used

| Dataset | Role | Why it is used this way |
|---|---|---|
| HLS (Landsat + Sentinel-2) | Defines treatment (cover, residue, tillage, bare fraction) and the yield outcome | 30 m, so it resolves individual fields |
| ECOSTRESS / OpenET | Water-use and heat-stress outcomes; ET-based moisture proxy | 70 m and 30 m, close to field scale |
| GPM IMERG | Defines drought and wet-year shocks; rainfall input to erosion, merged with CoCoRaHS | Resolution is too coarse for point-scale storm intensity, so it is used regionally |
| SMAP L4 | Regional moisture modifier and live signpost. Percentiles come from the 1979-present NLDAS climatology | At 9 km a pixel covers about 150 fields, so it cannot produce a field-level effect |
| GRACE-FO | Groundwater stress modifier (sets weights for water-limited regions) | Resolution is about 300 km |
| SRTM / 3DEP | Slope, curvature and wetness confounders; tillage-erosion term | Terrain drives both adoption and outcomes |
| NASA POWER / NLDAS | Daily weather modifiers; 40-year climatology for signposts | Long record makes the percentiles stable |
| NEX-GDDP-CMIP6 | Future distributions of effect modifiers | Supplies the climate-transport layer |
| GEDI | Not used for cover crops (it cannot see canopies under 1 m). Optional landscape context only | Removed after red-team review |

---

## 4. What the farmer sees (card format; numbers illustrative)

Field header:
- **Season ribbon:** bare and residue fractions by month, rainfall-shock risk, heat-stress windows from ECOSTRESS, continuity of pest host crops.
- **2045 outlook:** from CMIP6.

For **Strategy 0 (current)** and **Strategies 1-3**, each card shows:
- **Why suggested:** the field's largest *measured* problem that the strategy targets.
- **Evidence badge:** Strong / Moderate / Thin / Beyond evidence. Each badge maps to a calibrated historical error rate.
- **Evidence sources:** number of twin fields of the same type, number of randomized trials, any quasi-experiment.
- **Benefits:** effect ranges *for this field type*, with measured outcomes in solid bars and modelled ones (N2O, nitrate) in striped bars.
- **Information gaps:** for example, whether the field is tiled, or rye biomass at termination.
- **Risks needing local review:** PRIM failure box in plain words ("costs yield mainly in cold *and* dry Aprils, about 1 in 6 years").
- **Signpost:** "If SMAP April root-zone moisture falls below the 20th percentile of the 1979-present record, terminate rye early." This is labelled as agronomic guidance, not an identified effect.
- **Next best step (value of information):** "A 6-acre paired strip trial for 2 seasons", with a link to Practical Farmers of Iowa or DIFM protocols.
- **Who pays:** EQIP 340 (Cover Crop), EQIP 328 (Conservation Crop Rotation), CSP, state insurance discounts.

Example strategies for a central-Iowa corn-soy field on a convex knoll:
1. Cereal rye before soybean.
2. **Reduced tillage / no-till on the knoll.** This targets tillage erosion, which Thaler et al. 2021 identify as the main cause of hilltop topsoil loss.
3. Prairie strips on the eroding knoll, which now have **Strong** evidence from the STRIPS randomized experiments.

Diversifying beyond corn-soy appears with Bowles et al. 2020 (maize-phase resilience in long-term trials) shown next to Kluger et al. 2025 (small or negative yield effect per rotation-year). Both are shown and neither is hidden.

---

## 5. Impact unlocks (the core of the pitch)

**Accounting rule:** tool impact = decisions changed x difference in causal effect x realistic uptake. Farm yield is netted against environmental services on acres steered away from cover crops. Practice-effect evidence from the literature is labelled as such, not as tool impact.

| Tier | Impact | Who | Mechanism | Evidence (practice level) |
|---|---|---|---|---|
| Farm | Stop the first bad cover-crop year that makes farmers quit | First-time adopters; 4.7% of cropland (17.99M ac) currently uses covers | Field-type effects show where covers cost yield; signposts trigger early termination | Deines 2023: average -5.5% maize / -3.5% soy, with strong variation by soil and weather |
| Farm | Capture the rotation benefit where it is largest, and see where heat erodes it | Continuous-corn growers | Precrop effect conditioned on temperature, transported to 2045 | Kluger 2022: about 1.02 t/ha corn rotation benefit, 1.18 t/ha in cool years vs 0.84 t/ha in hot years |
| Farm | Drought resilience as evidence specific to the field type | Farmers, lenders, the USDA Risk Management Agency (RMA) | Yield anomaly in shock years by regime | Bowles 2020: maize phase +28%, drought losses 14-90% smaller (long-term trials) |
| Landscape | Stop *future* hilltop topsoil loss | Hillslope farms, downstream water utilities | Tillage + water erosion model; reduced-till regime | Thaler 2021: about 35% of Corn Belt has lost its A horizon, about $2.8B/yr (context: past damage, not recoverable) |
| Landscape | Infiltration, flood buffering, less nitrate | Downstream communities | Measured ET/SAR proxies; modelled nitrate routed to HUC-12 watersheds | Basche & DeLonge 2019: about 35% infiltration gain from cover crops, 59% for perennials+covers. Thapa 2018: about 56% less nitrate leaching under non-legume covers |
| Public money | More conservation per EQIP/CSP dollar | NRCS, taxpayers | Policy trees on effects by field type, valued with doubly-robust policy evaluation on held-out regions | Cover crops are EQIP's top-funded practice. Stetter 2022: individual agri-environment effects differ strongly from averages |
| Insurance | Evidence for resilience-linked premium discounts | RMA, insurers | Field-type resilience effects; quasi-experiment from the discount rollout | Won 2024 (county-level, correlational): higher cover-crop adoption linked to lower prevented-planting losses. Sawadgo 2024: only about 11% of Iowa discount acres were additional, which argues for targeting |
| Learning system | Randomized evidence that grows with use | Researchers, extension | Value of information routes uncertain farmers into strip trials; results tighten everyone's estimates | Practical Farmers of Iowa and DIFM networks show farmer-run randomized trials are practical |
| Global | Same engine wherever HLS and crop maps exist; voice delivery | Smallholders via NASA Harvest partners | HLS + global crop maps; numbers only from tool calls | Odisha RCT shows voice advisory *reaches* millions cheaply (+1.7% yield, generic advice). It is delivery evidence only |

**Headline claim:** COUNTERFIELD moves conservation dollars, insurance discounts and farmer effort from "pay for the practice everywhere" to "pay where the measured benefit is positive". Every farm it cannot yet advise confidently becomes new randomized evidence.

---

## 6. Validation plan

1. **Out-of-time hindcast (headline demo).** Train on 2016-2021. Rank regimes for the **2022-2023 Midwest droughts**. Score against what actually happened (Kendall tau, top-1 regret, calibration). Compare against a rule-based selector and a correlational ML model.
2. **Known-effect recovery.** Reproduce Deines 2023 and Kluger 2022 within their confidence intervals. Recover the effects from randomized trials (Practical Farmers of Iowa, LTAR, STRIPS) through the hybrid estimator.
3. **Semi-synthetic benchmark.** Inject known effects and spatially structured hidden confounders, then measure how often each badge pattern is wrong. Use this to calibrate the badges.
4. **Negative controls.** Placebo "effects" on pre-adoption yields and with placebo dates.
5. **Spatial-temporal block cross-validation.** Hold out whole HUC-8 watersheds and whole years.
6. **Ground truth for each layer.**
   - NASS county yields
   - OpenET vs ECOSTRESS vs flux towers
   - IMERG vs CoCoRaHS
   - SMAP vs NRCS SCAN probes
   - cover and tillage detection vs OpTIS maps and NAIP spot checks
   - nitrate and sediment vs USGS NWIS
7. **Human review.** An agronomist panel rates 50 cards. Farmers are tested on whether they understand the natural-frequency risk wording.

Removed after red-team review:
- the 2012 hindcast (HLS did not exist then)
- the 2019 hindcast (prevented-planting status caused cover-crop seeding, so outcome drove treatment)
- SMAP-derived field outcomes
- per-twin soil-carbon direction claims

---

## 7. Demo moments

1. **"Meet your twins."** Click a real Iowa field. Neighbouring fields of the same type that switched rotation light up. A synthetic-control chart shows the field tracking its twins before the switch and diverging after it, with an interval and an evidence count.
2. **"Press hindcast."** The model is frozen in 2021 and ranks rotations for the 2022-23 drought, then the real outcomes are revealed next to the rule-based selector's ranking.
3. **"Drag to 2045."** A CMIP6 slider. The rotation benefit shrinks with heat. Kansas and Missouri field types that already live Iowa's 2045 climate light up as analogs. With no analogs, the area turns hatched: "beyond evidence, strip trial recommended".
4. **"The plan keeps watching."** A live signpost fires from the current SMAP anomaly.
5. **"Zoom to the county."** A three-line policy tree for EQIP targeting, with its estimated value per dollar.
6. **Close.** A 20-second voice summary in which every number comes from a tool call.

---

## 8. Hackathon slice vs full vision

**Hackathon build:** 6-10 central Iowa counties, 2016-2024, three supported regimes (rotation vs continuous corn, cover crop vs none, reduced vs conventional tillage), 1-2 fully worked hero fields.

| Component | Hackathon version |
|---|---|
| Treatments | CDL sequences + HLS NDVI/NDTI unmixing (Planetary Computer, already tested) |
| Outcomes | HLS yield proxy calibrated to NASS; OpenET ET; drought-year anomaly |
| Confounders | gNATSGO soils, NASADEM terrain, NASA POWER weather (all tested) |
| Causal | Causal forest / DR-learner + non-absorbing DiD; trial priors from published Practical Farmers of Iowa / STRIPS results |
| Uncertainty | Split-conformal + overlap count + one semi-synthetic calibration run |
| Hindcast | 2022-23 drought, precomputed |
| Climate | NEX-GDDP-CMIP6, 3 models x 2 scenarios; county-level analog search |
| Decision | 6 preference cards; one PRIM failure box; value-of-information heuristic |
| UI | MapLibre map, twins highlight, synthetic-control chart, cards, 2045 slider, voice |

**Full vision:** all CONUS fields; program instruments (Iowa discount, PCCP, EQIP cutoffs); national strip-trial network integration; RMA evidence package; signpost alert service; agronomist console; global extension.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Unmeasured confounding (operator skill, tile drainage, N rate) | Quasi-experiments, trial anchoring, negative controls, sensitivity Gamma on every card |
| Survivorship bias from disadoption | Intent-to-treat at first adoption; disadoption modelled as an outcome; inverse-probability-of-censoring weights |
| Noisy per-field outcomes vs effects of 3-5% | Report by field type. Per-field results only once yield-monitor data are uploaded |
| Thin overlap for diverse rotations | Restricted menu, analogs, and "no evidence yet: here is the cheapest trial" |
| Climate extrapolation | Out-of-support flag, analog fallback, hatching, spread across climate models kept separate |
| LLM inventing numbers | Numbers only through tool calls; hatched estimates escalate to an agronomist |
| Misuse by landlords or insurers | Farmer-owned data, consent, aggregate-only third-party outputs |

## 10. Claims still to verify before citing

- PCCP "12.2M acres vs 5M forecast": not verified. Confirm with RMA/FSA or drop it.
- Kluger 2025 "median precrop benefit 4.5%" and its volume/article number.
- Won 2024: the paper says "1%" or "1 percentage point"? Check the full text.

Full v1 design, red-team report and all five original concepts: see `research/`.
