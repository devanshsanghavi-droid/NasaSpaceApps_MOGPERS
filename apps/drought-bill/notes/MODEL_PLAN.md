# Drought Bill model plan (coordinator spec for the `model` module)

Inputs: `data/processed/*.parquet` per CONTRACTS.md (rma_county_year, hazard_county_year, usdm_county_year, modis_county_year,
cdl_county_year, cdl_county_static, county_static, nass_county_year, nass_prices, cmip6_deltas, counties).
Outputs: `model/*.py`, `model/outputs/*.json|parquet`, and the web files in `web/data/` per CONTRACTS.md.

## 1. Panel
- Unit: county x crop year, 2001-2024 (2025 only if RMA marks it complete; otherwise exclude and say so).
- Main outcome: `lcr_drought` = drought indemnity / liability (price-normalized). Fit separately for
  `all` principal crops and for `corn` (the within-crop outcome is what isolates a rotation effect from crop-mix effects).
- Keep county-years with insured_acres >= a floor (e.g. 2,000 acres) and liability > 0; weight by liability (or insured acres).
- Hazard features (NASA): spi_jja, prcp_jul_mm anomaly, edd30_jja, gwetroot_jja / pct, vpd_jja, hazard_z; MODIS vci_jul_aug only as
  a validation/ablation feature (it is an outcome-like measure observed in season; not usable for forward climatology).
- Static modifiers: aws0_150, irrigated_share (also RMA irrigated_insured_share), county climatology (1991-2020 mean JJA precip, mean edd30).

## 2. Loss model (prediction)
- M0 baseline_mean: county mean lcr through 2020 (shrunk to state mean for thin counties).
- M1 baseline_hazard_only: pooled model on hazard features only (no county effects).
- M2 main: county fixed effects (or county random intercepts) + nonlinear hazard response + hazard x modifier interactions
  (aws, irrigation, diversity). Implement as (a) a penalized GLM / Tweedie or log-linear on lcr with splines, and/or (b) LightGBM
  Tweedie with hazard + static + county mean-encoding trained only on <= 2020. Pick the best on a validation split inside 2001-2020
  (e.g. leave-year-out CV on training years), then evaluate once on 2021-2024.
- Out-of-time test: train through 2020, predict 2021, 2022, 2023, 2024 from observed NASA hazard in those years.
  Metrics at county level (MAE, RMSE, R2, Spearman) on $/ac and on lcr, and aggregate totals (predicted vs actual total drought
  indemnity $ for the region and by state) with intervals (block bootstrap over training years). Compare to M0 and M1.

## 3. Rotation-diversity effect (causal, with honest diagnostics)
Question: does higher rotation diversity (CDL 5-yr window, measured BEFORE the loss year) reduce drought loss sensitivity?
- Treatment D: div_shannon_5y (window ending year t-1, i.e. lagged, so it is pre-determined), alternative n_crops_5y, share_3plus.
- Outcome: corn lcr_drought (and all-crop as secondary).
- Estimators: (i) FE regression with hazard x D interaction, county and state-year FE, clustered SE by county;
  (ii) DML (econml LinearDML / CausalForestDML) with X = modifiers (aws, irrigation, climatology), W = hazard, year, state,
  corn_share, insured-acre share; report the CATE of D on lcr in high-hazard years (hazard_z > 1) and in normal years.
- Diagnostics (must be reported in VALIDATION.md):
  * Confounding: diversity is higher in drier western counties (KS/SD/NE wheat-sorghum systems) and correlated with irrigation,
    soils and climate. Show the raw correlation, then after controls. Within-county (FE) variation is small: report its SD.
  * Overlap: distribution of D conditional on climate zone/state; trim to common support.
  * Placebo: effect of D in low-hazard years (should be ~0); effect on excess-moisture losses (should be ~0 if it's drought-specific);
    lead test (D measured after year t should not "predict" year-t loss beyond lagged D).
  * Sensitivity: Cinelli-Hazlett robustness value / partial R2 benchmark against an observed confounder (e.g. irrigation share).
  * Compare magnitude with the trial prior (Bowles et al. 2020: diverse rotations cut maize drought-year yield losses 14-90%).
- For the app: the "diversity effect" used in sliders/strategies = observational estimate WITH its CI, displayed next to the trial
  range; if the observational estimate is not distinguishable from zero or has the wrong sign, say so plainly and use the trial prior
  as the scenario assumption, labelled as such.

## 4. Simulation: expected annual bill and tails
- For each county, apply the fitted loss function to each year's NASA POWER hazard 1981-2024 (holding today's county
  characteristics fixed) -> 44 simulated loss-cost years. Expected bill = mean; 1-in-5 = 80th pct; 1-in-10 = 90th pct.
- $/acre = lcr x county mean liability per insured acre 2020-2024 (nominal $; state it). Intervals from parameter bootstrap.
- Taxpayer share = county subsidy/premium (2020-2024) x bill (actuarial approximation: premiums ~ expected losses; document).
- 2045: shift the hazard climatology with NEX-GDDP-CMIP6 deltas per GCM (delta method on input variables, recompute features),
  rerun; ensemble median and range for ssp245 and ssp585.
- Slider: bill under the county's 2022 hazard (and 2012 hazard) as a function of diversity across the observed range.

## 5. Strategy engine (farmer view)
Per county and current rotation class (corn-soy, continuous corn, 3+ crop, with perennial):
- S0 current, S1 corn-soy-small grain (diversity up), S2 cereal-rye cover crop, S3 drought-tolerant swap (sorghum or wheat in
  place of part of corn, where RMA/NASS show the crop is grown in that state), S4 continuous corn -> corn-soy (when current is CC).
- delta_bill from the diversity effect (S1, S4), from county RMA crop-specific drought loss costs (S3), and from evidence priors
  for S2 (likely thin / no reliable drought-loss effect: say so; do not invent a reduction).
- delta_income: NASS county yields (2019-2023 mean) x state prices; operating cost differences from USDA ERS Commodity Costs and
  Returns if obtainable (www.ers.usda.gov is reachable); otherwise revenue only, labelled.
- Evidence grade, why, benefits, gaps, risks needing local review, in plain language.
