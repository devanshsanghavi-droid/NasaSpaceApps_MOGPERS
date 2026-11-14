# COUNTERFIELD
### A counterfactual twin for every U.S. field, built from 17 years of natural experiments recorded by NASA satellites

---

## 1. Name and one-line pitch

**COUNTERFIELD.** For any U.S. field, COUNTERFIELD shows what a different rotation actually did on real neighbouring fields that already made the switch. It also shows how confident that evidence is, whether the effect still holds in the field's 2045 climate, and which NASA signal should prompt the farmer to change plan.

**The 30-second story for judges.** Every season, millions of U.S. farmers run an uncontrolled agronomic experiment, and NASA satellites record it: what was planted, how long the soil sat bare, how much water the crop used, and how it came through drought. Nobody has turned that record into evidence for the next farmer. Today's tools are either lookup tables ("bare Nov-Apr, so plant rye") or process-model simulations. COUNTERFIELD treats about 16M fields x 17 years as one large natural experiment. It uses causal machine learning to estimate, field by field, what each rotation would do there, and it says honestly where the evidence runs out.

---

## 2. The core insight

**Recommending a rotation is a causal question, not a classification or lookup.** The question a farmer asks is: "What would *my* field's yield, water balance, soil and drought behaviour be under a rotation it has not grown?" A table cannot answer that, and neither can a correlation. Fields that already diversify differ from those that do not in soil, drainage, landscape position and operator, so the naive finding that "diverse fields yield more" is confounded.

The new move is to treat the satellite archive as a source of **identified counterfactuals**, then turn those into **monitored, preference-aware, climate-transported plans**:

1. **Treatment** is a multi-year regime plus a continuous dose. A regime looks like "corn-soy-oat/clover for 4 years". The dose is bare-soil days weighted by IMERG rainfall erosivity, measured from HLS spectral unmixing. Neither is a yes/no flag.
2. **Outcomes** are measured by NASA sensors, not simulated: yield (SCYM on HLS), water use (OpenET/ECOSTRESS), soil-water storage and drydown (SMAP), SOC trend direction (the Landsat bare-soil archive), erosion exposure, and drought-year resilience.
3. **Three independent identification strategies** must agree before the tool shows a number: staggered DiD, generalized synthetic control, and causal forests / DML.
4. **Honest uncertainty.** Each field gets conformal intervals, a confounding "flip strength", evidence density from overlap, and an out-of-climate-support flag. That uncertainty is converted into actions (strip trials, soil cores) rather than hidden.
5. **Plans, not answers.** Effects are transported to NEX-GDDP-CMIP6 futures and become **adaptation pathways with NASA signposts**. One example: "if SMAP April root-zone moisture is below the 20th percentile in 2 of 3 years, switch to early rye termination." The satellites keep monitoring the plan after delivery.

### Contrast with what exists

| Existing tool / company | What it does | Why it isn't this |
|---|---|---|
| Midwest Cover Crops Council selector, NRCS guides | Matches species to planting windows | A lookup table: the "if-else" baseline |
| Regrow (OpTIS + DNDC) | Detects practices from satellites, then simulates outcomes | The counterfactual is a process-model run, reported mostly at watershed scale |
| CIBO (SALUS), Indigo Ag (DayCent) | Simulation-based MRV against a "common practice" baseline | Modelled baseline, not identified from data. Built for carbon accounting, not farmer rotation choice |
| Farmers Business Network | Peer benchmarking | Correlational, with no causal identification |
| ClimateAi | Climate-risk forecasting | Says nothing about what a management change would *cause* |
| NASA Acres | Observation layers (tillage, cover crops, SOC metrics) | Monitoring, not a decision engine. COUNTERFIELD consumes these layers |
| Deines et al. 2023; Kluger et al. 2022, 2025 (Stanford/Lobell) | Proved that causal forests on satellite data recover rotation and cover-crop effects | Retrospective research papers, not a prospective per-field planner. No regimes, conformal intervals, climate transport or pathways |

What COUNTERFIELD adds on top of that lineage:
- dynamic multi-year regimes estimated with dynamic DML;
- multi-outcome NASA measurement, beyond yield;
- the three-estimator agreement rule;
- PPI and trial hybrids to correct measurement error;
- per-field conformal intervals plus flip strength;
- CMIP6 transport with CONUS analog fallback;
- signpost pathways and BOPE preference learning;
- policy trees for program targeting.

---

## 3. System architecture

```
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L0  FIELD UNIVERSE & TREATMENT HISTORY                                                  │
 │  USDA CSB polygons (~16M, 2008-) + CDL ──► crop-sequence transformer embedding          │
 │  HLS L30/S30 30 m ──► spectral unmixing (green veg / residue / bare soil fractions)     │
 │  GPM IMERG 30-min ──► EI30 erosivity  ⇒  DOSE = Σ bare-fraction·erosivity (per season)  │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L1  HARMONIZATION VIA OBSERVATION OPERATORS (field polygon = common unit)               │
 │  SMAP L4 9 km / SPL2SMAP_S 3 km ─ footprint operator + representativeness error         │
 │  ECOSTRESS 70 m ─ overpass-time operator (instantaneous → daily via evaporative frac.)  │
 │  IMERG 0.1° ─ Bayesian merge w/ PRISM + CoCoRaHS     │  MODIS/VIIRS LST ─ frost clim.   │
 │  Confounders: SSURGO/gSSURGO, SRTM/3DEP (slope, curvature, TWI), NASA POWER/NLDAS,      │
 │  GRACE-FO regional TWS, NLCD/LANDFIRE, Prithvi-EO-2.0 pre-period HLS embeddings         │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L2  OUTCOME SENSORS (measured)                         │  SIDECAR (modeled, labelled)   │
 │  Yield: SCYM on HLS + weather, NASS-calibrated         │  KGML emulator: N2O, nitrate   │
 │  Water: OpenET 30 m ET, ECOSTRESS ET/ESI/LST           │  leaching, SOC magnitude;      │
 │  Storage: SMAP drydown τ, storm-response gain          │  calibrated to L3 effects at   │
 │  SOC: Landsat bare-soil trend (direction only)         │  population level              │
 │  Erosion exposure; drought/wet-year yield anomaly      │                                │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L3  CAUSAL CORE  — three estimators must agree                                          │
 │  (a) Staggered DiD / event study (Callaway–Sant'Anna)   (b) Generalized synthetic       │
 │  control per field (Xu)   (c) Causal forest / R-learner / dynamic DML (CATE w/ weather  │
 │  modifiers)  + spatial-block cross-fitting, spatial basis confounders, negative controls │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L4  BIAS & UNCERTAINTY: PPI (gold: yield monitors/RMA/LTAR) · Kluger trial-sat hybrid · │
 │  Lei–Candès weighted conformal · Jin–Ren–Candès flip strength · overlap/evidence density│
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L5  CLIMATE TRANSPORT: NEX-GDDP-CMIP6 (multi-GCM, SSP2-4.5/5-8.5) → effect-modifier     │
 │  distributions → integrate CATE; out-of-support? → CONUS ANALOG TWINS (fields whose     │
 │  current climate = this field's 2045 climate, same soil/terrain) or hatch               │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L6  DECISION: BOPE preference cards → utility + CVaR dial → Pareto set (≥3 + current)   │
 │  PRIM failure boxes → adaptation pathways w/ SMAP/ECOSTRESS signposts · VOI/EVSI        │
 │  Landscape: Athey–Wager policy trees (EQIP/CSP) · "who pays" panel · SWAT+ HUC-12       │
 └───────────────┬────────────────────────────────────────────────────────────────────────┘
                 ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ L7  DELIVERY: map + twins + strategy cards · season ribbon · voice/SMS (numbers only    │
 │  via tool calls) · agronomist review queue · farmer uploads → tighter intervals + PPI   │
 └────────────────────────────────────────────────────────────────────────────────────────┘
        ▲                                                                  │
        └──── each season: new HLS/SMAP/ECOSTRESS obs + farmer data ───────┘ (signposts re-evaluated)
```

### Layer detail

**L0: Field universe and treatment.**
- *Inputs:* USDA NASS Crop Sequence Boundaries (CSB; about 16M CONUS polygons, 2008 to present), the annual CDL, and the HLS L30/S30 time series (30 m, 2-3 day revisit).
- *Methods:*
  - A small transformer over CDL crop tokens produces a sequence embedding per field-year.
  - HLS pixels are unmixed into green-vegetation, crop-residue and bare-soil fractions, using NDTI/cellulose-sensitive SWIR bands with field-specific endmembers. This gives continuous bare-soil and residue fractions rather than an NDVI threshold.
  - Winter cover detection is cross-checked against OpTIS-style greenness.
  - The **bare-soil dose** is the daily bare fraction times IMERG-derived EI30 erosivity, summed per season.
- *Outputs:* a regime label for every field-year (e.g. CC, CS, CS+rye, CSO+clover), a continuous dose, cover biomass, and planting and harvest dates.

**L1: Harmonization with observation operators.** Data is not crudely resampled to one grid. Each sensor gets an operator H that maps it to the field polygon and carries an error term.
- *SMAP L4 root-zone (9 km) and SPL2SMAP_S (3 km):* the field inherits the footprint value. The **representativeness-error variance** is estimated from the sub-footprint variance of SMAP-HydroBlocks 30 m (2015-2019), conditioned on SSURGO texture and TWI.
- *ECOSTRESS 70 m:* matched at its actual (variable) overpass time. Instantaneous ET is scaled to daily through evaporative fraction. ECOSTRESS is the diurnal heat-stress channel; OpenET monthly 30 m ET is the primary water-use outcome.
- *IMERG 0.1°:* merged with PRISM and CoCoRaHS through a Bayesian error model. Its 30-minute intensities feed EI30.
- *Confounders and modifiers:*
  - SSURGO/gSSURGO (AWC, Ksat, OM, drainage class, NCCPI);
  - SRTM/3DEP (slope, profile curvature, TWI, flow accumulation);
  - NASA POWER/NLDAS daily weather;
  - GRACE/GRACE-FO regional storage anomaly as a water-scarcity modifier only, because at about 300 km it is never treated as field-scale;
  - NLCD/LANDFIRE landscape context;
  - **Prithvi-EO-2.0 embeddings of the pre-period HLS trajectory**, a learned summary of hard-to-measure field condition for donor matching and nuisance models.

**L2: Outcome sensors.** Each outcome carries its measurement-error model into L4.

| Outcome | Sensor/method | Notes |
|---|---|---|
| Yield | SCYM on HLS + weather, calibrated to NASS county yields | Debiased with PPI against yield-monitor and RMA gold data |
| Water use and stress | OpenET 30 m ET, ECOSTRESS ET/ESI/LST | Water productivity = yield / ET |
| Soil-water storage / infiltration signature | SMAP L4 RZSM, SMAP-HydroBlocks 30 m; IMERG storm events | Drydown timescale τ and storm-response gain. Flagged *experimental* outside 2015-2019 |
| SOC trend | Landsat/HLS bare-soil composites since 1986 | **Direction only** (magnitude R² ≈ 0.16, Broeg 2024) |
| Erosion exposure | Dose x LS factor (3DEP) x K (SSURGO) | RUSLE-style C-factor from measured cover, not a lookup |
| Resilience | Yield anomaly in IMERG/ECOSTRESS-defined drought and excess-wet years | Feeds the insurance evidence package |
| Pest-cycle proxy | Host-crop continuity (field years-in-a-row + neighbour continuous-corn share) | Pest pressure is *not* observed. Effect is measured on yield, conditioned on host continuity |
| Frost / heat exposure | MODIS/VIIRS night LST climatology, cold-air pooling from 3DEP, CMIP6 tails | Map layer and effect modifier |

**Sidecar: modeled, not observed.** A knowledge-guided ML emulator (in the style of KGML-ag / KGML-ag-Carbon) covers N2O, nitrate leaching and SOC magnitude. At population level it is calibrated so that its predicted yield and water effects match the L3 causal estimates. It appears in a separate, visibly labelled band and never on the "measured" axis. This is how the legume N2O trade-off (+36%, He et al. 2025) reaches the cards without being presented as observed.

**L3: Causal core.**
- (a) **Staggered DiD / event studies** (Callaway & Sant'Anna 2021) on fields that switched in different years, compared against not-yet-switched fields under the same weather. "Switch" means the first sustained adoption (3 or more years). Reversion is treated as censoring, and disadoption is itself analysed as an outcome.
- (b) **Generalized synthetic control** (Xu 2017) per target field. Donors are matched on the pre-switch Prithvi embedding trajectory, soil, terrain and weather. The result is a literal counterfactual time series for *this* field.
- (c) **Causal forest / R-learner** (Wager & Athey 2018; Chernozhukov et al. 2018) estimates the CATE as a function of soil, terrain and growing-season weather. **Dynamic DML** (Lewis & Syrgkanis 2021) handles multi-year regimes in which last year's crop shapes this year's confounders. The continuous dose uses a DML dose-response.
- *Safeguards:*
  - spatially blocked cross-fitting;
  - spatial-basis confounder adjustment (Gilbert et al.);
  - operator-cluster fixed effects from contiguous CSB parcels;
  - negative-control outcomes (pre-switch yields and pre-switch drydown);
  - exposure mapping for spillovers (neighbour continuous-corn share for rootworm).
- *Agreement rule:* a number is shown only if all three estimators agree in sign and their intervals overlap. Disagreement is surfaced as an information gap.

**L4: Bias and uncertainty.**
- **PPI** (Angelopoulos et al. 2023) uses a gold sample (yield monitors, RMA unit yields, LTAR and long-term trials) to debias effects estimated from 16M proxy-labelled fields.
- The **Kluger-Owen-Lobell hybrid estimator** pools randomized trials and satellite data (13% lower RMSE than trials alone, 26% lower than satellites alone).
- **Lei-Candès weighted conformal** intervals give per-field counterfactual intervals, with GeoConformal distance weighting for spatially varying width.
- **Jin-Ren-Candès conformal sensitivity analysis** gives the "flip strength": how strong an unmeasured confounder would have to be to reverse the recommendation.
- **Overlap/positivity** diagnostics give an evidence density: how many genuinely similar fields tried the alternative.

**L5: Climate transport.**
- NEX-GDDP-CMIP6 (0.25°, multi-GCM, SSP2-4.5 and SSP5-8.5) is bias-corrected to PRISM. Per-field growing-season effect-modifier distributions (heat degree-days, April-June rain, VPD) are built for 2035-2055, and the CATE is integrated over them, keeping GCM spread separate.
- If the future modifiers fall outside the historical support, the system retrieves **CONUS climate-analog twins**: fields whose *current* climate matches this field's 2045 climate, on similar soil and terrain, within the CDL/CSB/SSURGO label system to avoid cross-continent confounding. It shows their observed regime effects, labelled as analog evidence.
- If no analogs exist either, the band is hatched and labelled "beyond the evidence".

**L6: Decision.**
- **BOPE preference cards** learn the utility weights and a CVaR risk level.
- Candidate regimes are the status quo plus at least 3 alternatives, chosen by a determinantal diversity selector over the Pareto set.
- **PRIM scenario discovery** on the per-field effect surface x CMIP6 ensemble produces plain-language failure boxes.
- Those boxes become **Dynamic Adaptive Policy Pathways** whose tipping points are NASA-observable signposts.
- **VOI/EVSI** ranks the information-gathering actions: a strip trial, a soil core at a GPS point, a yield-monitor upload, or confirming tile drainage.
- At landscape level, **Athey-Wager policy trees** give interpretable EQIP/CSP targeting rules. Sediment and nitrate are routed to HUC-12 outlets with SWAT+.
- A **"who pays" panel** attaches the existing levers: EQIP practice 340 (Cover Crop), 328 (Conservation Crop Rotation), CSP, and insurance discounts where offered.

**L7: Delivery.**
- A "Your field and its twins" map.
- A season ribbon: bare windows coloured by erosivity, vulnerable windows from ESI and frost, and the pest-continuity count. This is the brief's "highlight bare-field periods", but produced from measured fractions rather than as the product itself.
- Strategy cards (Section 6).
- Voice/SMS mode in which an LLM may only verbalize numbers returned by tool calls into L3-L6. Hatched estimates always trigger an "ask your agronomist" escalation.
- Farmer uploads tighten that field's interval and add to the PPI gold sample.

---

## 4. The intelligence

### What is learned or inferred (none of it hand-written rules)
| Component | Learned object | Method |
|---|---|---|
| Treatment measurement | Bare / residue / green fractions; cover presence and biomass | Spectral unmixing + supervised classifier; GEDI L4A footprints anchor biomass |
| Field representation | Crop-sequence embedding; pre-period field-condition embedding | Transformer over CDL tokens; Prithvi-EO-2.0 |
| Nuisance models | Propensity of adopting a regime; outcome surfaces | Gradient boosting / forests, spatially cross-fitted |
| Effects | Field-level CATE by regime and by weather; dynamic regime effects; dose-response for bare-soil exposure | Causal forest, R-learner, dynamic DML, DiD, synthetic control |
| Bias correction | Measurement-error rectifier | Prediction-powered inference; trial-satellite hybrid |
| Uncertainty | Per-field intervals; confounding robustness | Weighted conformal; conformal sensitivity (flip strength) |
| Climate | Future modifier distributions; analog neighbours | Bias-corrected NEX-GDDP-CMIP6; kNN on soil, terrain and climate |
| Failure conditions | Readable boxes in the scenario space where a regime loses | PRIM |
| Farmer utility | Weights across income, risk, soil, water, labour; CVaR α | BOPE / Bradley-Terry on pairwise cards |
| Targeting | Which field types should receive which incentive | Athey-Wager policy trees |

### How uncertainty is decomposed and communicated
Six separate sources are tracked and never merged into one error bar:
1. **Sampling / estimation:** conformal interval width.
2. **Measurement:** the PPI correction and its added variance.
3. **Hidden confounding:** flip strength. Below about 1.5 means "a modest unmeasured factor could reverse this".
4. **Evidence density:** the number of overlapping twins and trials.
5. **Estimator disagreement:** DiD vs synthetic control vs forest.
6. **Climate:** GCM spread, plus an out-of-support or analog flag.

The farmer sees:
- **Evidence badges:** *Strong* (many twins, estimators agree, flip strength ≥2), *Moderate*, *Thin*, *Beyond the evidence* (hatched).
- **Natural frequencies:** "In about 2 of 10 years (dry springs) this costs you about $15-25/acre; in the other 8 it is roughly break-even or better."
- **Intervals:** e.g. "+9 to +21 bu/ac (80%)".
- **A hidden-factor gauge** in words: "A hidden factor would need to make switchers about 2.3x more likely to succeed to reverse this."
- **Measured vs modeled:** solid bars for measured outcomes, striped bars for modeled ones (N2O, nitrate).

### How farmer priorities enter
- **Pairwise future cards (BOPE).** The farmer answers about 8 "which future would you rather have?" cards, each a short income and soil trajectory anchored on their own current rotation's income as the reference point. For example: "steadier income, slightly lower average" vs "higher average, 1 bad year in 8". A Bradley-Terry/GP utility model learns the weights and a CVaR α.
- Test-retest consistency is checked. If the answers are inconsistent, the tool falls back to showing the full Pareto set without ranking.
- Hard constraints are elicited in conversation: equipment (no small-grain header), labour windows, landlord lease terms, irrigation rights.
- Priorities change the *ranking and highlighting* of strategies. They never change the evidence.

### How local experts validate
- **Review queue:** every hatched, thin-evidence or low-flip-strength card is routed to an extension agent or agronomist console showing the twins, the estimator disagreement and the failure boxes. The expert can annotate, override or endorse, and every action is logged.
- **Turning gaps into actions:** VOI produces a concrete request rather than a dead end. For example: "a 5-acre paired strip trial on the NW hilltop, or one soil core at this GPS point, has the highest expected value." Results flow back as gold data.
- **Farmer knowledge as data:** "tile-drained", "ponded May 2019", "yield was 182" are entered as covariates or gold labels, not just comments.
- **Framing:** decision support only. The current rotation is always shown, and regret is shown in both directions.

---

## 5. Impact unlocks

*Estimates labelled "our estimate" are extrapolations, not measured results.*

| Tier | Impact | Who | Mechanism | Scale (numbers) | Evidence |
|---|---|---|---|---|---|
| **Farm** | Stop the cover-crop yield penalty that drives disadoption | Corn and soy growers; first-time adopters | Per-field CATE shows where covers cost yield (good soils, dry springs, cool mid-seasons) and where they are neutral or positive. Signposts trigger early termination in dry Aprils | Average losses of 5.5% for maize and 3.5% for soy after 3+ years of covers, varying strongly with soil and weather. Press coverage put the average corn penalty at about $40/ac. Adoption is 4.7% of cropland (17.99M ac). Our estimate: avoiding half the penalty on mistargeted acres is worth tens to hundreds of $M/yr and removes the main reason farmers quit | Deines et al. 2023; ERS Census chart 108950 |
| **Farm** | Capture the rotation benefit where it is largest, and see where warming erodes it | Continuous-corn and simple-rotation growers | Precrop CATE conditioned on temperature and rain, transported under CMIP6 | Corn rotation benefit about 1.02 t/ha (about 16 bu/ac), falling from 1.18 t/ha in the coolest quintile to 0.84 t/ha in the hottest. Roughly $55-85/ac where it applies. Diversifying beyond two crops often gives small or negative *yield* effects, so its case rests on resilience and soil | Kluger, Owen & Lobell 2022; Kluger, Di Tommaso & Lobell 2025 |
| **Farm** | Drought and wet-year resilience as a measured, field-specific counterfactual | Farmers, RMA, lenders | Synthetic-control yield anomaly in IMERG/ECOSTRESS-defined drought and wet years, by regime | Diverse rotations: +28% mean maize yield and 14-90% smaller drought-year losses across 11 long-term North American sites | Bowles et al. 2020 |
| **Landscape / watershed** | Cut erosion where topsoil is actually disappearing | Hillslope farmers, downstream utilities, Gulf hypoxia | Erosivity-weighted bare dose x 3DEP convex curvature locates eroding positions. Regime effects on dose and SOC-trend direction there | About 35±11% of Corn Belt cultivated area has lost its A horizon, giving about 6% yield loss and $2.8±0.9B/yr | Thaler, Larsen & Yu 2021 |
| **Landscape / watershed** | Infiltration and flood buffering; nitrate reduction | Downstream communities, drinking-water utilities | Measured SMAP storage signature, plus modeled nitrate (sidecar) routed to HUC-12 via SWAT+ | Cover crops and perennials raise infiltration about 59% on average (89 studies). Non-legume covers cut nitrate leaching about 56% | Basche & DeLonge 2019; Thapa, Mirsky & Tully 2018 |
| **Financial: program targeting** | More conservation per EQIP/CSP dollar | NRCS, state programs, taxpayers | Athey-Wager policy trees on per-field CATE plus benefit-per-dollar ranking | Cover crops: EQIP's top-funded practice FY2014-2025. About $126M in cover-crop payments in 2019. WRI reverse auction: about 7x phosphorus reduction per $ vs standard EQIP. Individual agri-environment effects differ markedly from averages | EWG EQIP data; WRI Conestoga; Stetter et al. 2022 |
| **Financial: insurance** | Resilience evidence for premium discounts and lower indemnities | RMA, insurers, farmers | Field-level resilience effects packaged as actuarial evidence. Prevented-planting and drought-year loss as outcomes | A 1 pp rise in county cover-crop adoption is associated with about $40M lower prevented-planting indemnities (2019). PCCP's $5/ac drew 12.2M acres vs a 5M forecast. Iowa's flat discount is about 11% additional, so targeting matters | Won et al. 2024; Aglasan et al. 2024; RMA PCCP; Sawadgo 2024 |
| **Financial: MRV / lending** | An empirical counterfactual baseline for carbon and Scope 3 programs | Registries, food companies, lenders | Synthetic-control baseline from real twins with conformal intervals and flip strength, cross-checking process-model baselines | Satellite SOC-trend *direction* is correct or stable for about 95% of monitored sites. Single-field SOC change is infeasible to measure by sampling, so the tool supplies direction plus pooled evidence | Broeg et al. 2024; Bradford et al. 2023 |
| **Global smallholder** | The same causal engine wherever HLS and crop maps exist, delivered by voice | Smallholders through NASA Harvest partners and extension services | Precrop causal ML already runs across breadbaskets. COUNTERFIELD adds intervals and voice delivery whose numbers come only from tool calls | Odisha voice advisory RCT: +1.7% yield, +4.1% harvest, 10% lower chance of severe crop loss. Reached more than 6.8M farmers after government handover. PxD's own estimate is $12-19 of benefit per $1. Median precrop benefit 4.5% across breadbaskets | Cole et al. 2025 (PxD); Kluger et al. 2025 |

**The headline impact claim, deliberately conservative.** COUNTERFIELD converts the U.S. conservation budget and crop-insurance discounts from paying for practices everywhere into paying where the measured benefit is positive. The same evidence also helps farmers avoid the first bad experience that makes them quit.

---

## 6. Rotation strategy output (what the farmer sees)

*Example field: central Iowa, 72 ac, corn-soybean since 2010, rolling with a convex NW knoll. The numbers below show the card format and are illustrative; the system computes them live.*

**Field header and season ribbon**
- Bare soil: about 205 days/yr. The erosivity-weighted dose is in the county's 85th percentile, driven by May-June storms on bare soy ground.
- Vulnerable windows: late-July heat and water stress (ECOSTRESS ESI below p20 in 4 of the last 10 years); the knoll is frost-safe; spring ponding in the SE swale (SMAP drydown τ in the slow tail).
- Pest continuity: neighbour continuous-corn share is 31%, so rootworm pressure is moderate.
- 2045 outlook (SSP2-4.5, multi-GCM): +11 hot days above 30°C in July; April-June rain +6% with more intense storms.

---

**Strategy 0: Keep corn-soybean (current)**
- **Why shown:** this is the baseline, and it is always first.
- **Evidence:** the field's own 15-year HLS/SMAP/OpenET record, plus 1,840 similar corn-soy fields.
- **Benefits:** familiar, no new equipment, and the corn-after-soy benefit already captured (+14 to +19 bu/ac vs continuous corn on similar fields).
- **Information gaps:** none major.
- **Risks needing local review:**
  - The knoll's erosion dose is high; SOC-trend direction there is *declining* (measured, direction only).
  - The rotation benefit shrinks in hot years. In 2045 hot-year frequency, the corn benefit falls by about a fifth (CMIP6 transport, *in support*).
- **Risk in plain words:** "In about 2 of 10 years, July heat costs you more than $40/ac. That stays the same or gets worse by 2045."

**Strategy 1: Corn-soybean + cereal rye before soybean, with satellite-triggered early termination**
- **Why suggested:** it cuts your largest measured problem, May-June bare soil on the knoll. Rye before *soy* carries a smaller penalty than rye before corn on fields like yours.
- **Evidence:** *Moderate-Strong.*
  - 312 twin fields switched between 2012 and 2020.
  - All three estimators agree in sign.
  - Flip strength 2.1.
  - The pattern matches Deines et al. 2023 (larger penalties in dry springs).
- **Benefits:**
  - Erosion exposure -35 to -45% (measured dose).
  - SMAP storage signature improves (drydown τ +8 to +15%, experimental outcome).
  - Soy yield -4.5% to +0.3% (80%).
  - Fewer excess-wet-year losses on twins.
  - SOC trend direction shifts from declining to stable on 64% of twins.
- **Information gaps:** rye biomass at termination on your soils (HLS can measure it after year 1); whether the SE swale is tiled (it changes the effect).
- **Risks needing local review:**
  - Failure box (PRIM): "rye costs yield mainly in Aprils that are both cold *and* dry (about 1 in 6 historical years, 12% of 2045 futures)."
  - **Signpost:** "if SMAP April root-zone moisture is below p20, terminate 14+ days before planting." The tool sends this alert each April.
- **Who pays:** EQIP practice 340 / CSP eligibility; insurance cover-crop discount where offered. The net economics show the yield penalty in red.

**Strategy 2: Extended rotation: corn-soybean-oat underseeded with red clover**
- **Why suggested:** breaks the 2-year rootworm/SCN host cycle, roughly halves bare days, and adds a legume N credit. Diverse rotations reduced drought-year losses in long-term trials (Bowles et al. 2020).
- **Evidence:** *Thin.*
  - 41 twin fields, plus long-term trial evidence pooled through the hybrid estimator.
  - DiD and the forest agree; synthetic control is wide.
  - Flip strength 1.4 (weak).
- **Benefits:**
  - Drought-year corn loss smaller (measured on twins, wide interval).
  - Erosion dose -50 to -65%.
  - Corn after clover needs less N (modeled).
  - Lower N2O than adding *more* legume cover with full N (modeled sidecar).
- **Information gaps:**
  - The yield effect per *rotation-year* may be small or negative; Kluger et al. 2025 found diversification beyond two crops often is.
  - Oat price and local straw market (AMS Market News is thin locally).
  - Equipment.
- **Risks needing local review:**
  - Income in the oat year depends on the local market.
  - Low flip strength means a factor such as operator experience could reverse the result.
  - **VOI:** "a 6-acre paired strip trial for 2 seasons is the best next step (expected value about $X/ac in avoided regret)."
- **Who pays:** EQIP 328 Conservation Crop Rotation.

**Strategy 3: Perennial or prairie strips on the eroding knoll (8% of field) + corn-soy elsewhere**
- **Why suggested:** the knoll is where topsoil loss concentrates (3DEP convex curvature plus the bare-soil dose; Thaler et al. 2021 mechanism).
- **Evidence:** *Beyond the evidence* (hatched). Too few twin fields have done this for a causal estimate.
- **Benefits:** large erosion reduction on the knoll (modeled); yield loss on low-productivity acres only.
- **Information gaps:** no measured yield or income effect. A soil core on the knoll would show whether the A horizon is already gone. VOI ranks this core first ("one $30 core at this GPS point").
- **Risks needing local review:** the whole card is routed to the agronomist queue; lease or landlord terms.
- **Who pays:** CSP / state buffer programs.

**Pathway map (bottom of screen).** Start on Strategy 1. "If ESI is below p20 in 2 of 3 Julys **and** strip-trial results are positive, move to Strategy 2. If the knoll core shows the A horizon is lost, add Strategy 3 there." Each year the plan is re-scored with new HLS, SMAP and ECOSTRESS data.

---

## 7. Validation plan

1. **Out-of-time hindcast harness (headline).**
   - Freeze all data at year T.
   - Rank regimes for the **2012 drought** using only 2008-2011 data, and for the **2019 wet spring / prevented-planting year** using data through 2018.
   - Score the predicted ranking against what actually happened on the fields that ran each regime: Kendall τ, top-1 regret, and calibration of the predicted drought-year anomaly.
   - Compare against two baselines: (i) a rule-based MCCC-style selector and (ii) a non-causal ML predictor trained on correlations.
2. **Spatial-temporal block cross-validation.** Hold out whole HUC-8 blocks and year blocks, so spatial autocorrelation cannot inflate the scores.
3. **Known-effect recovery.**
   - Reproduce Deines et al. 2023 (about -5.5% maize / -3.5% soy, with its heterogeneity pattern) and the Kluger et al. 2022 corn-precrop effect within confidence intervals.
   - Recover effects from long-term randomized rotation trials (the Bowles et al. network, LTAR sites) through the hybrid estimator.
4. **Semi-synthetic benchmark.** Inject known heterogeneous effects into real covariates and outcomes, including spatially structured hidden confounders. Check bias, coverage, and whether flip strength flags the confounded cases.
5. **Negative controls and placebos.** Check for "effects" on pre-switch yields and pre-switch drydown, placebo switch dates, and placebo outcomes. A non-null result marks the estimate as biased.
6. **Conformal coverage audit.** Check empirical 80% coverage on held-out field-years, stratified by evidence badge and region.
7. **Ground truth for each measurement layer.**
   - Yield: NASS QuickStats county aggregation (SCYM sums vs county yields), plus a yield-monitor and RMA gold sample.
   - ET: OpenET vs ECOSTRESS cross-check; OpenET accuracy against flux towers (Volk et al. 2024).
   - Precipitation: IMERG vs CoCoRaHS gauges.
   - Soil moisture: SMAP vs in-situ networks (NRCS SCAN) and SMAP-HydroBlocks.
   - Cover-crop and residue detection vs OpTIS maps and NAIP spot checks.
   - Streamflow and nitrate checks for the watershed layer against USGS NWIS.
8. **Climate-transport check.** Pseudo-future test: train on cooler years and predict effects in the hottest years, which stand in for future conditions. Verify that the analog-twin fallback beats naive extrapolation.
9. **Human validation.** Agronomist panel review of 50 cards (agree / disagree / unsafe), and farmer comprehension testing of the natural-frequency risk statements.

---

## 8. Demo moments for judges

1. **"Meet your twins"** (about 40 s).
   - Click a real Iowa field. The map dims and about 50 real neighbouring fields light up: same soil, slope and pre-2014 satellite trajectory, each of which switched rotation.
   - A synthetic-control panel animates the field's real HLS greenness, SMAP storage and yield against the twin-built counterfactual. The lines track before the switch and diverge after it.
   - Every number carries an interval, an evidence count and a flip-strength gauge.
2. **"Press hindcast"** (about 30 s).
   - The model is frozen with only pre-2012 data and ranks rotations for the 2012 drought. The screen then reveals what actually happened on those fields.
   - Side by side, it shows how the rule-based selector would have ranked them. This is the validity proof.
3. **"Drag to 2045"** (about 30 s).
   - Move the NEX-GDDP-CMIP6 slider. The corn-rotation benefit shrinks with heat.
   - Where the field leaves historical support, real Kansas and Missouri fields that already live Iowa's 2045 climate light up as analog evidence. Where no analogs exist, the band turns hatched: "beyond the evidence, strip trial recommended."
4. **"The plan keeps watching"** (about 20 s). A pathway metro map with a live signpost: "SMAP April root-zone moisture is below p20 this year, so terminate rye early."
5. **"Zoom to the county"** (about 20 s). A three-line policy tree says which field types EQIP should fund for which practice, with estimated benefit per dollar vs first-come allocation, and the "who pays" stack per field.
6. **Close.** The same recommendation plays as a 20-second plain-language voice message, in which every number comes from a tool call.

---

## 9. Hackathon MVP (36 h) vs full vision

### What we actually build
**Scope:** 6-10 central Iowa counties (on the order of 10^4-10^5 CSB polygons), 2008-2023, with 3 regimes that have real support: continuous corn vs corn-soy, cover crop vs none, and small-grain insertion. 1-2 hero fields are fully worked.

| Component | MVP implementation | Real or stubbed |
|---|---|---|
| Field universe | CSB + CDL for the counties; crop-sequence features (one-hot n-grams instead of a transformer) | Real |
| Bare-soil dose | HLS (via Earth Engine or earthaccess) NDVI + NDTI linear unmixing with 3 endmembers; IMERG daily erosivity proxy | Real, simplified |
| Outcomes | Peak GCVI/NDVI yield proxy calibrated to NASS county yields; OpenET monthly ET; SMAP L4 RZSM anomaly; drought-year anomaly (2012) | Real |
| Confounders | gSSURGO (AWC, OM, drainage, NCCPI), SRTM slope and curvature, NASA POWER weather | Real |
| Causal core | `grf` causal forest; `did` (Callaway-Sant'Anna) event study; augmented synthetic control for the hero fields; spatially blocked folds; one negative-control test | Real |
| Uncertainty | Split-conformal intervals on DR-learner pseudo-outcomes; a simplified sensitivity-based flip strength; overlap count | Real, simplified |
| Hindcast | Precomputed 2012 ranking from 2008-2011 data, scored on actual 2012 outcomes vs a rule baseline | Real (the key credibility piece) |
| Climate | NEX-GDDP-CMIP6, 3 GCMs x 2 SSPs, growing-season summaries; kNN analog search over CONUS counties for climate, soil and terrain | Real, county-level analogs |
| Pathways | One PRIM run on the hero field's CATE x weather surface → one signpost | Real, single field |
| Preferences | 6 pairwise cards → Bradley-Terry weights → re-ranked cards | Real, simple |
| VOI | Heuristic: rank actions by expected narrowing of the interval / chance of a flip | Simplified |
| N2O / nitrate sidecar | Meta-analysis priors (He et al. 2025; Thapa et al. 2018), labelled "modeled" | Stub, honestly labelled |
| Policy tree | Depth-2 policy tree on county CATEs for cover crops | Real, small |
| UI | Map (MapLibre/deck.gl), twins highlight, synthetic-control chart, cards, slider; TTS reading JSON fields | Real |

**Team split and schedule.**
- **Hours 0-10:** data pull and harmonization (2 people).
- **Hours 6-22:** causal core and hindcast (2 people).
- **Hours 10-28:** UI and cards (1-2 people).
- **Hours 22-30:** climate, analogs and PRIM.
- **Hours 30-36:** demo polish and the validation slide.

All heavy computation is precomputed to static tiles and JSON, so the demo runs offline.

### Full vision
All CONUS CSB fields; dynamic DML regimes; Prithvi embeddings; PPI with a national gold sample; Kluger hybrid with LTAR trials; full observation operators; KGML sidecar; SWAT+ HUC-12 routing; RMA evidence package; a seasonal signpost alert service; agronomist console; global extension via HLS and global crop maps with voice partners.

---

## 10. Key risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Unmeasured, non-smooth confounding (operator skill, N rate, tile drainage, seed) | Biases effects; spatial smoothing will not fix it | Operator-cluster fixed effects, negative controls, flip strength on every card, farmer-reported tile/N as covariates, trial hybrid |
| Weak overlap for diverse rotations | The tool will often say "no evidence" | Restrict the menu to supported regimes; analog twins; convert gaps into VOI-ranked strip trials. "No evidence, here is the cheapest way to get it" becomes a feature |
| Proxy-outcome error (SCYM explains a minority of variance; CDL misclassification of small grains and thin covers) | Attenuates effects toward zero | PPI with a gold sample, NASS calibration, unmixing-based treatment, sensitivity to misclassification rates |
| Experimental outcomes (SMAP storage signature only validated in 2015-2019; SOC magnitude) | Overclaiming | Label as experimental; use SOC direction only; no single-field SOC numbers |
| Climate extrapolation | Precise-looking but unidentified numbers | Out-of-support flag, analog fallback, hatching, GCM spread kept separate |
| Interference and market feedback (pest spillover, price effects of widespread switching) | SUTVA violations | Exposure mapping for neighbour host continuity; prices from AMS shown as a scenario slider, not a forecast |
| False precision in decision outputs (regret dollars) | Erodes trust | Ranges and natural frequencies only; regret shown both ways; the current rotation always shown |
| Preference elicitation for low-literacy users picks up framing effects | Wrong ranking | Anchor on the farmer's own income; consistency checks; fall back to the unranked Pareto set; co-design with extension staff |
| LLM voice layer could invent numbers | Safety | Numbers only via tool calls; refuses free numerics; escalation on hatched estimates |
| Misuse of per-field counterfactuals by landlords, insurers or lenders | Farmer harm | Farmer-owned data, consent, aggregate-only outputs for third parties, a typed claim registry |
| Hackathon compute | Demo fails | Small county scope, precomputed tiles, offline demo |

---

## 11. References (carried from inputs)

**Causal and statistical methods**
- Lewis, G., Syrgkanis, V. (2021). Double/Debiased ML for Dynamic Treatment Effects. NeurIPS. arXiv:2002.07285
- Callaway, B., Sant'Anna, P.H.C. (2021). Difference-in-differences with multiple time periods. J. Econometrics 225(2):200-230. doi:10.1016/j.jeconom.2020.12.001
- Xu, Y. (2017). Generalized synthetic control method. Political Analysis 25(1):57-76. doi:10.1017/pan.2016.2
- Wager, S., Athey, S. (2018). Estimation and inference of heterogeneous treatment effects using random forests. JASA 113(523). doi:10.1080/01621459.2017.1319839
- Chernozhukov, V. et al. (2018). Double/debiased machine learning. Econometrics Journal 21(1). doi:10.1111/ectj.12097
- Athey, S., Wager, S. (2021). Policy Learning With Observational Data. Econometrica 89(1):133-161. doi:10.3982/ECTA15732
- Lei, L., Candès, E.J. (2021). Conformal inference of counterfactuals and individual treatment effects. JRSS-B 83(5):911-938. arXiv:2006.06138
- Jin, Y., Ren, Z., Candès, E.J. Sensitivity analysis of individual treatment effects: a robust conformal inference approach. arXiv:2111.12161
- Angelopoulos, A.N. et al. (2023). Prediction-powered inference. Science 382:669-674. doi:10.1126/science.adi6000
- Gilbert, B., Datta, A., Casey, J.A., Ogburn, E.L. A causal inference framework for spatial confounding. arXiv:2112.14946
- Lou, Luo & Meng (2024). GeoConformal prediction. arXiv:2412.08661
- Stetter, C., Mennig, P., Sauer, J. (2022). Heterogeneous impacts of agri-environment schemes. Eur. Rev. Agric. Econ. 49(4):723-759

**Decision science**
- Lin, Astudillo, Frazier & Bakshy (2022). Preference Exploration for Efficient Bayesian Optimization with Multiple Outcomes (BOPE). AISTATS. arXiv:2203.11382
- Chow, Tamar, Mannor & Pavone (2015). Risk-Sensitive and Robust Decision-Making: a CVaR Optimization Approach. NeurIPS. arXiv:1506.02188
- Lempert, Bryant & Bankes (2008). Comparing Algorithms for Scenario Discovery (PRIM). RAND WR-557
- Haasnoot et al. Dynamic Adaptive Policy Pathways (overview chapter). https://link.springer.com/chapter/10.1007/978-3-030-05252-2_4

**Satellite agronomy and causal precedent**
- Deines, J.M. et al. (2023). Recent cover crop adoption is associated with small maize and soybean yield losses in the United States. Global Change Biology 29(3):794-807. doi:10.1111/gcb.16489
- Kluger, D.M., Owen, A.B., Lobell, D.B. (2022). Combining randomized field experiments with observational satellite data to assess the benefits of crop rotations on yields. Environ. Res. Lett. arXiv:2112.13700
- Kluger, D.M., Di Tommaso, S., Lobell, D.B. (2025). Precrop Payoffs. Environ. Res. Lett. 20:114037. arXiv:2506.02384
- Lobell, D.B. et al. (2015). A scalable satellite-based crop yield mapper. Remote Sensing of Environment 164:324-333. doi:10.1016/j.rse.2015.04.021
- Broeg, T. et al. (2024). Spatiotemporal monitoring of cropland SOC changes from space. Global Change Biology. PMC11626691
- Vergopolan, N. et al. (2021). SMAP-HydroBlocks, a 30-m satellite-based soil moisture dataset for CONUS. Scientific Data 8:264. doi:10.1038/s41597-021-01050-2
- Szwarcman, D. et al. Prithvi-EO-2.0. arXiv:2412.02732
- Thrasher et al. (2022). NASA Global Daily Downscaled Projections, CMIP6. Scientific Data 9:262. doi:10.1038/s41597-022-01393-4
- Volk et al. (2024). Assessing the accuracy of OpenET satellite-based evapotranspiration data. Nature Water. doi:10.1038/s44221-023-00181-7
- Melton et al. (2022). OpenET. JAWRA 58(6). doi:10.1111/1752-1688.12956
- Liu et al. (2024). Knowledge-guided ML can improve carbon cycle quantification in agroecosystems (KGML-ag-Carbon). Nature Communications. doi:10.1038/s41467-023-43860-5
- Liu et al. (2022). KGML-ag. Geoscientific Model Development 15:2839
- Fitzpatrick & Dunn (2019). Contemporary climatic analogs for 540 North American urban areas. Nature Communications 10. doi:10.1038/s41467-019-08540-3
- USDA NASS Crop Sequence Boundaries (Hunt et al. 2024). https://www.nass.usda.gov/research-and-science/crop-sequence-boundaries

**Agronomic and impact evidence**
- Bowles, T.M. et al. (2020). Crop-rotation diversification increases agricultural resilience. One Earth 2(3):284-293. doi:10.1016/j.oneear.2020.02.007
- Thaler, E.A., Larsen, I.J., Yu, Q. (2021). The extent of soil loss across the US Corn Belt. PNAS 118(8):e1922375118. doi:10.1073/pnas.1922375118
- He, Lu & Cowie (2025). Optimizing cover cropping application for sustainable crop production (271 studies). npj Sustainable Agriculture. doi:10.1038/s44264-025-00050-8. *The brief attributes these numbers to "Nature Sustainability 2023". That is a different paper, Vendig et al. 2023, doi:10.1038/s41893-023-01131-7, which covers SOC and yield.*
- Basche & DeLonge (2019). Infiltration meta-analysis. PLOS ONE 14(9):e0215702. doi:10.1371/journal.pone.0215702
- Thapa, Mirsky & Tully (2018). Cover crops reduce nitrate leaching. J. Environ. Qual. 47:1400-1411. doi:10.2134/jeq2018.03.0107
- Bradford et al. (2023). Feasibility of quantifying SOC stock change through empirical sampling. Dataset doi:10.5061/dryad.z08kprrjp
- Aglasan, Rejesus, Hagen & Salas (2024). Cover crops, crop insurance losses, and resilience. Am. J. Agric. Econ. 106(4):1410-1434. doi:10.1111/ajae.12431
- Won, Rejesus, Goodwin & Aglasan (2024). Cover crop use and prevented planting losses. Am. J. Agric. Econ. 106(2):659-683. doi:10.1111/ajae.12396
- Sawadgo (2024). Are crop insurance discount programs for cover crops effective? Agricultural & Environmental Letters 9:e20125. doi:10.1002/ael2.20125
- USDA RMA PCCP 2021 enrollment. https://www.rma.usda.gov/news-events/news/2022/washington-dc/producers-crop-insurance-receive-premium-benefit-cover-crops
- USDA ERS chart of note 108950 (cover crops 17.99M acres, 4.7% of cropland). https://ers.usda.gov/data-products/charts-of-note/108950
- USDA ERS chart of note 114076. https://www.ers.usda.gov/data-products/charts-of-note/114076
- EWG EQIP data. https://oembed.ewg.org/node/8271
- WRI, Paying for Environmental Performance: Reverse Auction. https://www.wri.org/research/improving-water-quality-3-3
- Cole, Goldberg, Harigaya & Zhu (2025). Ama Krushi Odisha RCT (PxD working paper). https://precisiondev.org/wp-content/uploads/2025/02/Odisha_RCT_02052025.pdf