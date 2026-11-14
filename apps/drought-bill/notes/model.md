# Module `model`: drought loss model, out-of-time validation, diversity effect, drought-bill simulation

Built 2026-11-14. Source for VALIDATION.md. Every number below is read from the output files named in each section
(all under `model/outputs/` unless stated); re-running the scripts regenerates them.

## Run order (re-runnable; Python `/home/user/venv-db/bin/python`, max 3 threads)
```
model/build_panel.py                  # hazard features from POWER daily + panel (~10 s)
model/fit_loss.py --stage cv          # model selection by leave-one-year-out CV, 2001-2020 only (incremental; ~20 min cold)
model/fit_loss.py --stage test        # ONE out-of-time test, 2021-2024, + 100 bootstrap refits per model (~12 min)
model/fit_loss.py --stage ablation    # reported-only ablations (MODIS, USDM, JJA-only, no static) (~10 min)
model/diversity_effect.py [--no-dml]  # rotation-diversity effect + diagnostics (~15 min with DML)
model/simulate.py --B 100 --B_future 30   # climatological bill, 100 bootstrap refits, 2045 (~10 min)
model/simulate.py --future-only       # re-run only the 2045 part (when more CMIP6 GCMs land)
model/export_web.py                   # web/data/county_bill.json, regional_summary.json, meta.json
```
Library files: `model/common.py` (paths, constants), `model/hazard_features.py` (feature engine + CMIP6 delta method),
`model/lossmodel.py` (encodings, candidate models).

## 1. Inputs and panel (`build_panel.py` -> `panel.parquet`, `hazard_features.parquet`)

**Outcome.** RMA drought indemnity (cause code 11) / liability = `lcr_drought` (loss cost ratio, price-normalised),
per county x crop year, for corn, soybeans, wheat, sorghum. RMA `all` is NOT used (it includes Pasture/Rangeland/Forage
rainfall-index acres). A **principal-crops** aggregate = sum of the four crop rows (dollars, acres summed; ratios
recomputed). Negative drought indemnity (claim reversals, 39 rows) is clipped to 0 for the model target. Dollars are
nominal. 2025 RMA is provisional and is excluded everywhere (training, test, bill); it is kept in the panel with
`provisional = True`.

**RMA county codes merged into Census counties** (found here; not in the rma notes): RMA uses rating-area codes that
are not Census counties, so they had no NASA POWER hazard or soils. They are summed into the Census county:
19156 -> 19155 (Pottawattamie IA, west part), 27112 -> 27111 (Otter Tail MN), 27120 -> 27119 (Polk MN),
46113 -> 46102 (old Shannon SD code -> Oglala Lakota). Together about $2.5B of principal-crop liability over 2001-2025.

**Panel rows** (`panel.parquet`, 70,384 rows, 2001-2025): corn 16,010; soybeans 15,361; wheat 13,771; sorghum 9,220;
principal 16,022. Columns: RMA sums (insured_acres, liability_usd, premium_usd, subsidy_usd, indem_total/drought/heat/
excess_moist_usd), lcr_drought, lcr_excess, lcr_total, drought_usd_per_ac, liab_per_ac, subsidy_share,
irrigated_insured_share (acre-weighted for principal), liab_share_<crop> (principal crop mix), static modifiers, all
hazard features, USDM (dsci_jja_mean, d2plus_pct_jja_max, dsci_mjjas_mean), MODIS (ndvi_jul_aug, vci_jul_aug, ndvi_z).

**Modelling sample.** Crop rows with liability > 0. Training rows also need insured_acres >= 1,000 (crop) — 34,476
crop rows in 2001-2020 (corn 12,334; soybeans 11,682; wheat 7,536; sorghum 2,924) and 41,370 in 2001-2024 for the
final fit. Prediction covers every crop row with liability > 0 (no floor), so totals include small counties.
Evaluation at county level uses principal-crop county-years with >= 2,000 insured acres. Sample weight =
liability / (region-year mean liability per acre), i.e. liability in "acre-equivalents", so high-price years
(2011-2014, 2021-2023) are not up-weighted.

**NASA POWER hazard features** (`hazard_features.py`). Recomputed from `power_daily_cells.parquet` (May-Sep) so that
the identical code can produce features from CMIP6-perturbed weather. Reproduction of the hazard module's columns
(max abs difference over all 30,015 county-years, `hazard_features_check.json`): prcp_jja 0.0001 mm, edd30_jja
0.00005, spi_jja 0.00005, gwetroot_jja_pct 0.00003, vpd 0.00005, hazard_z 0.00005 — i.e. float32 rounding only.
All anomalies/percentiles/z-scores use the observed 1991-2020 climatology of the county's POWER cell.

| feature | definition |
|---|---|
| spi_jja, spi_mj | gamma SPI of Jun-Aug / May-Jun precipitation (MERRA-2 bias-corrected, via POWER) |
| prcp_{jja,jul,aug,mj}_anom_pct | % anomaly vs 1991-2020 mean |
| edd30_jja, edd30_jja_anom, edd30_jul_anom | single-sine degree days > 30 C, level and anomalies |
| tmax_jja_anom, vpd_jja_anom | anomalies of mean Tmax and FAO-56 VPD |
| gwetroot_jja_pct, gwetroot_mj_pct | percentile of root-zone wetness (Jun-Aug / May-Jun) vs 1991-2020 |
| gwetroot_{jja,mj,jul_aug}_anom | anomalies of root-zone wetness |
| z_neg_spi_jja, z_edd30_jja, z_neg_gwetroot_jja, hazard_z | the hazard module's components and composite |
| hazard_z_mjja | extra composite adding z(-spi_mj) and z(-gwetroot_mj) (spring drought, e.g. IL/MO 2023) |
| clim_prcp_jja_mm, clim_edd30_jja, clim_gwetroot_jja | 1991-2020 climatology (static) |

Static modifiers: aws0_150_mm, aws0_100_mm, nccpi (SSURGO via SDA), irrigated_share (Census of Ag),
irrigated_insured_share (RMA sobtpu, time-varying). MODIS and USDM are used only in ablations (section 2.5).

## 2. Loss model and out-of-time validation (`fit_loss.py`)

### 2.1 Candidates and selection (CV inside 2001-2020 only)
Every candidate predicts crop-row lcr; predictions are converted to dollars with that row's liability and summed to
the principal-crops county-year. Leave-one-year-out (LOYO) CV over the 20 training years. **Selection rule (fixed
before any test-year evaluation): lowest pooled county-level RMSE of principal-crop $/insured acre over the 20 folds.**
Test years 2021-2024 were evaluated once, after selection (`--stage test`). The candidate list grew in three batches,
each informed only by CV results of the previous batch (recorded in `cv_results.json`):
batch 1 (county mean encoding, year term, small feature set, state code, leaves/trees/Tweedie power, spline GLM);
batch 2 (after batch 1 showed the county-mean encoding hurts: no-encoding variants and a hazard-relative
credibility factor); batch 3 (lower Tweedie power x credibility factor). Nothing else was tried.

- **M0 baseline_mean**: county x crop mean lcr over training years (equal weight per year), shrunk to the state x crop
  mean with k = 5 pseudo-years.
- **M1 baseline_hazard_only**: LightGBM Tweedie (power 1.5, 400 trees, 15 leaves, lr 0.03, min_child 50,
  subsample/colsample 0.8) on the NASA POWER hazard features + crop code. No county information.
- **Selected model `ratio_haz_static_a05_tvp12`**: two stages.
  Stage 1 = LightGBM Tweedie (power 1.2, same tree settings) on hazard features + static modifiers + climatology +
  crop code. Stage 2 = county x crop credibility factor F = (sum actual lcr + k mu) / (sum out-of-fold stage-1 lcr +
  k mu), k = 5 pseudo-years, mu = the county-crop's mean stage-1 prediction; out-of-fold = 5 folds of training years.
  Prediction = stage1 x F^0.5 (F clipped to [0.05, 20]; F = 1 for unseen county-crops). F measures how a county's
  insured losses compare with what its weather predicts (management, unit structure, coverage levels) and, unlike a
  plain county mean, is not inflated by the county's 2012 exposure.

LOYO CV, principal crops, county-years with >= 2,000 acres (n = 12,461 county-years over 20 folds); "yr APE" = median
absolute % error of the region-year total; bias = pooled total bias.

| candidate | RMSE $/ac | MAE $/ac | R2 | Spearman | within-year Spearman | yr APE % | bias % | corn RMSE |
|---|---|---|---|---|---|---|---|---|
| baseline_mean (M0) | 30.48 | 14.31 | 0.013 | 0.056 | 0.250 | 135.0 | 3.3 | 50.96 |
| baseline_hazard_only (M1) | 21.42 | 7.58 | 0.513 | 0.742 | 0.581 | 30.2 | -13.4 | 36.98 |
| lgb_haz_static | 17.86 | 6.40 | 0.661 | 0.775 | 0.665 | 37.0 | -19.3 | 30.14 |
| lgb_haz_static_enc (k=5) | 19.73 | 6.72 | 0.587 | 0.782 | 0.669 | 36.8 | -22.5 | 33.86 |
| lgb_haz_static_enc_k2 | 19.50 | 6.69 | 0.596 | 0.782 | 0.671 | 37.7 | -21.6 | 33.43 |
| lgb_haz_static_enc_k10 | 19.53 | 6.70 | 0.595 | 0.780 | 0.669 | 35.5 | -21.9 | 33.47 |
| lgb_haz_static_enc_year | 21.00 | 6.89 | 0.532 | 0.795 | 0.670 | 36.3 | -31.0 | 35.29 |
| lgb_small_static_enc | 20.59 | 6.98 | 0.550 | 0.775 | 0.655 | 37.2 | -22.8 | 35.23 |
| lgb_haz_static_enc_state | 19.65 | 6.73 | 0.590 | 0.778 | 0.666 | 36.8 | -21.6 | 33.72 |
| lgb_haz_static_enc_l31 | 19.57 | 6.57 | 0.593 | 0.787 | 0.672 | 35.9 | -25.2 | 33.29 |
| lgb_haz_static_enc_n800 | 19.61 | 6.59 | 0.591 | 0.789 | 0.673 | 32.2 | -25.6 | 33.35 |
| lgb_haz_static_enc_tvp12 | 18.80 | 6.65 | 0.624 | 0.773 | 0.662 | 38.1 | -17.8 | 32.46 |
| lgb_haz_static_enc_tvp18 | 21.38 | 6.95 | 0.514 | 0.783 | 0.664 | 40.3 | -29.9 | 36.82 |
| glm_spline_enc (Tweedie GLM, splines) | 26.58 | 9.30 | 0.249 | 0.713 | 0.541 | 53.3 | -15.9 | 44.91 |
| lgb_haz_static_tvp12 | 16.61 | 6.34 | 0.707 | 0.767 | 0.658 | 36.8 | -12.6 | 27.56 |
| lgb_haz_static_l31 | 17.36 | 6.25 | 0.680 | 0.779 | 0.667 | 35.9 | -21.1 | 28.93 |
| lgb_haz_static_n800 | 17.64 | 6.24 | 0.669 | 0.784 | 0.670 | 35.7 | -22.0 | 29.28 |
| lgb_haz_static_state | 18.26 | 6.47 | 0.646 | 0.776 | 0.664 | 38.4 | -20.0 | 30.82 |
| ratio_haz_static_a1 | 17.40 | 6.62 | 0.678 | 0.780 | 0.675 | 35.1 | 3.7 | 27.94 |
| ratio_haz_static_a05 | 16.47 | 6.26 | 0.712 | 0.781 | 0.677 | 39.7 | -10.0 | 27.45 |
| lgb_haz_static_tvp11 | 16.72 | 6.41 | 0.703 | 0.763 | 0.651 | 34.9 | -11.3 | 27.65 |
| **ratio_haz_static_a05_tvp12 (selected)** | **15.75** | 6.22 | **0.736** | 0.773 | 0.669 | 37.3 | -5.5 | **25.75** |
| ratio_haz_static_a03_tvp12 | 15.91 | 6.24 | 0.731 | 0.772 | 0.667 | 36.9 | -8.7 | 26.20 |
| (ablation, not eligible) + USDM | 18.42 | 6.46 | 0.639 | 0.811 | 0.703 | 29.6 | -13.3 | 30.97 |

Pooled RMSE is dominated by the 2012 fold. The selected model's held-out 2012 region total: predicted $9.27B vs actual
$9.13B (M1: $8.24B). Held-out region totals by year (selected model, $M predicted / actual): 2002 769/1,066;
2003 481/962; 2006 889/836; 2011 1,269/1,140; 2012 9,267/9,128; 2013 1,983/2,736; 2017 837/571; 2020 817/518.

### 2.2 Out-of-time test: train 2001-2020, predict 2021-2024 from observed NASA POWER hazard
`validation.json`, `web/data/hindcast.json`, county predictions in `hindcast_county.parquet`. County level = principal
crops, $/insured acre, county-years with >= 2,000 acres (n = 2,525 over 4 years). Metric CIs: 1,000 bootstrap
resamples of counties (95%).

| model | MAE $/ac | RMSE $/ac | R2 | Spearman | total bias 2021-24 |
|---|---|---|---|---|---|
| **model (selected)** | **15.18** [14.05, 16.33] | **31.24** [28.63, 33.89] | **0.356** [0.315, 0.401] | **0.783** [0.767, 0.800] | -32.6% |
| baseline_mean | 22.11 [20.92, 23.39] | 36.38 [33.86, 38.82] | 0.127 [0.103, 0.151] | 0.402 [0.366, 0.435] | -17.9% |
| baseline_hazard_only | 17.28 [15.99, 18.62] | 35.44 [32.53, 38.32] | 0.171 [0.135, 0.211] | 0.705 [0.682, 0.727] | -42.8% |

Paired differences (model minus baseline, county bootstrap): vs baseline_mean MAE -6.95 [-7.54, -6.38], RMSE -5.18
[-6.24, -4.12]; vs baseline_hazard_only MAE -2.11 [-2.59, -1.64], RMSE -4.22 [-5.03, -3.37]. The model is better than
both baselines on every county-level metric; the differences exclude zero.

On loss cost ratio (lcr): model MAE 0.0339, RMSE 0.0739, R2 0.404, Spearman 0.809; baseline_mean 0.0471 / 0.0849 /
0.216 / 0.519; hazard-only 0.0383 / 0.0846 / 0.221 / 0.749. Corn only ($/corn insured acre): model MAE 19.5, RMSE
44.3, R2 0.331, Spearman 0.762; baseline_mean 31.1 / 50.9 / 0.115 / 0.282; hazard-only 22.0 / 50.4 / 0.133 / 0.695.

**Region totals (principal crops, nominal $; lo/hi = 5th-95th pct of 100 block-bootstrap refits):**

| year | actual | model | baseline_mean | baseline_hazard_only |
|---|---|---|---|---|
| 2021 | $1.294B | $1.426B [1.216, 1.827] | $1.731B [0.895, 2.594] | $0.935B [0.759, 1.602] |
| **2022** | **$3.737B** | **$2.121B [1.769, 2.870]** | $2.258B [1.173, 3.387] | $1.999B [1.433, 2.539] |
| **2023** | **$4.169B** | **$2.160B [1.777, 2.907]** | $2.390B [1.263, 3.583] | $1.958B [1.420, 2.963] |
| 2024 | $0.927B | $1.119B [0.877, 1.406] | $1.936B [1.021, 2.890] | $0.904B [0.665, 1.147] |

Per-year county metrics (model): 2021 RMSE 16.6, Spearman 0.74, total bias +10%; 2022 RMSE 45.3, Spearman 0.84,
bias -43%; 2023 RMSE 38.2, Spearman 0.63, bias -48%; 2024 RMSE 10.4, Spearman 0.67, bias +21%.

**Honest reading.** The model ranks counties well in the drought years (Spearman 0.84 in 2022) and beats both
baselines at county level, but it **under-predicts the 2022 and 2023 totals by about half** (2022: $2.12B vs $3.74B;
2023: $2.16B vs $4.17B), and the bootstrap intervals do not cover the actual totals. The baseline_mean total looks
closer only because it predicts roughly the same ($1.7-2.4B) every year (its 2024 total is +109% off).
By state (`hindcast.json` by_state), the 2022 miss is mostly KS (pred $0.69B vs actual $1.56B), SD ($0.28B vs $0.65B)
and NE ($0.64B vs $0.93B); the 2023 miss is KS ($0.53B vs $1.38B), NE ($0.20B vs $0.64B), MN ($0.35B vs $0.65B) and
IA ($0.43B vs $0.72B). By crop, 2023 wheat was $0.23B predicted vs $0.75B actual (the KS 2023 winter-wheat failure
came from a fall-winter-spring drought that the May-Aug POWER features do not see), and corn $1.17B vs $2.15B.
These were multi-season, back-to-back droughts; the USDM ablation (below), whose index has multi-month memory,
recovers much more of them. Adding antecedent (prior fall/winter) NASA POWER features is the obvious fix, but it was
identified only after looking at the test years, so it was **not** added (that would be tuning on the test).

**Interval coverage.** County-level 90% bootstrap intervals cover the actual value in only 39.0% of test county-years:
they are parameter-uncertainty intervals (block bootstrap over training years), not predictive intervals. All lo/hi
in the web files have this meaning and are labelled so.

### 2.3 Ablations (`ablations.json`; reported only, never used for selection)
Selected model with one change; CV = LOYO 2001-2020 pooled RMSE; test = 2021-2024 county RMSE; totals $M pred/actual.

| variant | CV RMSE | test RMSE | 2022 total | 2023 total |
|---|---|---|---|---|
| selected (NASA POWER + static) | 15.75 | 31.24 | 2,121 / 3,737 | 2,160 / 4,169 |
| + MODIS NDVI/VCI Jul-Aug (NASA) | 13.85 | 30.23 | 1,826 / 3,737 | 1,263 / 4,169 |
| + USDM DSCI (not NASA) | 16.25 | 25.32 | 2,794 / 3,737 | 3,292 / 4,169 |
| JJA-only hazard (drop May-June features) | 15.10 | 32.02 | 1,976 / 3,737 | 2,062 / 4,169 |
| no static modifiers | 18.01 | 32.95 | 1,887 / 3,737 | 2,012 / 4,169 |

- MODIS VCI is an in-season outcome-like signal, available only 2001+, and cannot be projected, so it is not in the
  headline model. It improves CV and county RMSE slightly but makes the 2022 and 2023 totals worse. Independent check of the NASA POWER hazard: Spearman(VCI Jul-Aug,
  hazard_z) = -0.42 and Spearman(VCI, lcr_drought) = -0.49 over 15,340 principal county-years 2001-2024
  (Spearman(hazard_z, lcr_drought) = +0.65).
- USDM is an expert blend with multi-month memory that partly reflects observed impacts, starts in 2000 (no
  1981-1999 climatology) and has no projection, so it cannot drive the 44-year simulation or 2045. Its test gain
  points to the missing antecedent-drought signal, not to a defect in the NASA data.
- JJA-only is slightly better in CV but worse on the test; the spring features stay (selection is by CV of the whole
  candidate, and the ablation is not a candidate).

## 3. Rotation-diversity effect (`diversity_effect.py` -> `diversity_effect.json`)
**Question.** Does higher crop-rotation diversity, measured BEFORE the loss year, reduce drought loss sensitivity?
**Sample.** Insured corn county-years with >= 1,000 acres and a CDL window with >= 500 cropland pixels: 7,463
county-years, 631 counties, 2013-2024 (the lagged 5-year window needs CDL 2008+, so 2012 is lost). Only 630 are
high-hazard (NASA POWER hazard_z > 1): 2013 25, 2016 1, 2017 15, 2018 20, 2020 43, 2021 157, 2022 195, 2023 158,
2024 16. Low-hazard placebo years (hazard_z < 0): 3,706.
**Treatments** (CDL window ending t-1). Primary = `share_3plus` (share of cropland pixels with >= 3 crop classes in the
window), following the CDL module: Shannon rewards evenness (clean corn-soy = 0.673), and Bowles' contrast is 2-crop vs
3-5 crop. Secondary = `n_crops_5y`, `div_shannon_5y`.
**Outcome** corn lcr_drought (weights = liability acre-equivalents); principal crops secondary.
**Main specification** y = a_county + g_state-year + b1 D + b2 D x H + b3 H + H x aws + H x irrigation + corn share
(CDL, t-1) + corn share x H, clustered SE by county; D centred. "Effect in high-hazard years" = b1 + b2 x mean H among
hazard_z > 1 rows (= 1.33), reported per +0.1 unit of D as % of the mean corn lcr in those rows (0.0708).
County FE and state-year FE are made full-rank by dropping each state's base year (county dummies are nested in
states; without this the clustered covariance is singular).

### 3.1 Confounding and overlap (primary share_3plus)
- Mean 0.206 (p10 0.041, p50 0.162, p90 0.452). SD: total 0.162, between counties 0.153, **within county 0.053
  (11% of the variance)**; after county + state-year FE the residual SD is 0.038 (R2 of D on the FE = 0.947).
- Across counties, share_3plus is higher where corn is a smaller share (Spearman -0.70 with corn share; -0.58 with
  continuous corn), soils hold less water (aws -0.45), summers are hotter (clim EDD +0.43) and drier (clim JJA precip
  -0.27), further west (longitude -0.32) and more irrigated (+0.20); county mean corn drought lcr +0.51. In high-hazard
  years the raw Spearman of D with corn lcr is +0.46. So the raw association is "more diverse = more loss", driven by
  the drier Plains counties.
- State p10/p50/p90 of county means: IA 0.03/0.07/0.16; IL 0.03/0.10/0.31; KS 0.16/0.28/0.54; MN 0.05/0.19/0.45;
  MO 0.12/0.19/0.35; NE 0.06/0.14/0.33; SD 0.10/0.28/0.61. Common support (overlap of the states' 5-95% ranges) is
  0.115-0.200 and holds only 23% of rows (IA 19%, IL 17%, KS 23%, MN 30%, MO 27%, NE 27%, SD 21%).
- Shannon by contrast is nearly unrelated to geography (Spearman with longitude +0.01, JJA climatology -0.01, mean
  corn lcr +0.05; within-county share 16%).
- CDL caveat (from the CDL module): 2008-2010 CDL labels more cropland as grass, so part of the 2012-2016 within-county
  diversity trend is a classification artifact; state-year FE absorb the common part only.

### 3.2 Estimates (corn; effect of +0.1 D in high-hazard years, % of mean loss cost; negative = protective)

| spec | n | D x H coef (SE) | effect, high-hazard (lcr per unit D) [95% CI] | % per +0.1 [95% CI] | effect, low-hazard [95% CI] |
|---|---|---|---|---|---|
| **share_3plus** (+0.1 = +10 pp of cropland in 3+ crop rotations) | | | | | |
| pooled: state-year FE + controls | 7,463 | +0.0396 (0.0131) | +0.082 [+0.037, +0.128] | +11.6% [+5.2, +18.1] | +0.008 [-0.000, +0.016] |
| **county FE + state-year FE (headline)** | 7,463 | +0.0444 (0.0130) | +0.089 [+0.033, +0.145] | **+12.6% [+4.6, +20.5]** | +0.005 [-0.039, +0.049] |
| PPML, county FE + state-year FE | 7,458 | +0.090 (0.306) | +0.431 [-1.017, +1.878] (log scale) | +4.4% [-9.7, +20.7] | |
| PPML, state-year FE + controls | 7,463 | -0.475 (0.268) | +0.597 [+0.066, +1.128] (log scale) | +6.1% [+0.7, +11.9] | |
| FE, spring-inclusive hazard (hazard_z_mjja) | 7,463 | +0.0496 (0.0128) | +0.105 [+0.048, +0.162] | +17.3% [+7.9, +26.8] | |
| FE, unweighted | 7,463 | +0.0154 (0.0128) | +0.070 [+0.017, +0.123] | +6.0% [+1.5, +10.6] | |
| FE, principal crops outcome | 7,499 | +0.0236 (0.0104) | +0.006 [-0.047, +0.059] | +0.8% [-6.3, +8.0] | |
| FE, common support only | 1,724 | +0.301 (0.159) | +0.604 [+0.100, +1.108] | +54.6% [+9.1, +100.2] | |
| FE, contemporaneous window (ends t; adds 2012) | 8,091 | +0.106 (0.021) | +0.298 [+0.179, +0.418] | +22.5% [+13.5, +31.5] | |
| **n_crops_5y** (+0.1 crop classes per pixel) | | | | | |
| pooled: state-year FE + controls | 7,463 | -0.0072 (0.0081) | -0.007 [-0.035, +0.021] | -1.0% [-5.0, +3.0] | |
| county FE + state-year FE | 7,463 | -0.0022 (0.0082) | +0.002 [-0.031, +0.034] | +0.2% [-4.3, +4.7] | |
| PPML, county FE + state-year FE | 7,458 | +0.015 (0.192) | | +0.4% [-7.9, +9.4] | |
| FE, principal crops outcome | 7,499 | -0.0077 (0.0065) | -0.037 [-0.067, -0.006] | -5.0% [-9.1, -0.9] | |
| FE, common support | 4,145 | -0.046 (0.031) | -0.138 [-0.236, -0.041] | -22.3% [-38.0, -6.5] | |
| FE, contemporaneous window (adds 2012) | 8,091 | +0.072 (0.016) | +0.210 [+0.136, +0.284] | +15.8% [+10.2, +21.4] | |
| **div_shannon_5y** (+0.1 Shannon) | | | | | |
| pooled: state-year FE + controls | 7,463 | -0.0740 (0.0169) | -0.129 [-0.188, -0.070] | -18.2% [-26.6, -9.9] | +0.010 [-0.002, +0.023] |
| county FE + state-year FE | 7,463 | -0.0613 (0.0181) | -0.103 [-0.173, -0.033] | -14.5% [-24.4, -4.7] | +0.013 [-0.038, +0.063] |
| PPML, county FE + state-year FE | 7,458 | +0.160 (0.399) | -0.165 [-1.976, +1.647] (log scale) | -1.6% [-17.9, +17.9] | |
| PPML, state-year FE + controls | 7,463 | -0.692 (0.456) | -1.120 [-2.068, -0.172] (log scale) | -10.6% [-18.7, -1.7] | |
| FE, hazard_z_mjja | 7,463 | -0.0490 (0.0171) | -0.073 [-0.139, -0.006] | -12.0% [-23.0, -1.1] | |
| FE, unweighted | 7,463 | -0.0591 (0.0163) | -0.079 [-0.144, -0.015] | -6.8% [-12.4, -1.3] | |
| FE, principal crops | 7,499 | -0.0500 (0.0143) | -0.134 [-0.197, -0.071] | -18.2% [-26.8, -9.7] | |
| FE, common support (0.528-0.682; 61% of rows) | 4,536 | -0.152 (0.037) | -0.364 [-0.531, -0.198] | -56.0% [-81.6, -30.3] | |
| FE, contemporaneous window (adds 2012) | 8,091 | +0.134 (0.031) | +0.427 [+0.278, +0.576] | **+32.2% [+20.9, +43.4]** | +0.109 [+0.039, +0.179] |

**DML** (econml 0.17; LightGBM nuisance models, 3-fold cross-fitting grouped by county; W = soils, irrigation,
climatology, corn share t-1, lon/lat, hazard components, year, state dummies; "Mundlak" adds county means of D, hazard
and leave-one-out outcome). % per +0.1 D of mean corn lcr, 95% CI:

| treatment | estimator | high-hazard (n=630) | low-hazard (n=3,706) | all |
|---|---|---|---|---|
| share_3plus | LinearDML (CATE linear in H) | -4.0% [-9.7, +1.8] | +32.1% [+7.8, +56.5] | -1.8% [-9.5, +5.9] |
| share_3plus | LinearDML + Mundlak | -21.1% [-38.2, -4.0] | +175% [+81, +270] | -9.0% [-29.3, +11.3] |
| share_3plus | CausalForestDML | -6.6% [-21.9, +8.7] | +16.0% [-62.6, +94.6] | +2.9% [-27.6, +33.4] |
| share_3plus | CausalForestDML + Mundlak | -29.1% [-69.8, +11.6] | +24.7% [-154, +203] | -3.1% [-74.8, +68.7] |
| n_crops_5y | LinearDML | -5.6% [-10.0, -1.2] | +16.9% [-2.2, +36.1] | -5.7% [-11.4, 0.0] |
| n_crops_5y | LinearDML + Mundlak | -5.6% [-15.1, +3.8] | +89.7% [+39.4, +140.1] | +2.3% [-9.0, +13.7] |
| div_shannon_5y | LinearDML | -15.2% [-24.6, -5.7] | +20.7% [-19.3, +60.6] | -18.2% [-29.5, -6.9] |
| div_shannon_5y | LinearDML + Mundlak | -12.9% [-30.8, +4.9] | +124% [+27, +222] | -3.7% [-24.2, +16.8] |
| div_shannon_5y | CausalForestDML | -26.7% [-52.9, -0.5] | -25.6% [-110.8, +59.6] | -16.8% [-60.5, +27.0] |
| div_shannon_5y | CausalForestDML + Mundlak | -30.3% [-80.9, +20.3] | +24.3% [-207, +256] | -1.3% [-84.0, +81.4] |

First-stage cross-fitted R2 (treatment): 0.82 (share_3plus), 0.76 (n_crops), 0.76 (Shannon); with Mundlak 0.94-0.97, so
little treatment variation is left. The large low-hazard "effects" (mean corn lcr in low-hazard years is 0.0027, so small
absolute differences become large %) show the DML designs are not clean either: where the high-hazard CATE is
protective, the low-hazard placebo is often significantly harmful.

### 3.3 Placebos, lead test, sensitivity

| check | share_3plus | n_crops_5y | Shannon |
|---|---|---|---|
| low-hazard years only, FE, D coef on drought lcr (n=3,706) | +0.0045 [-0.0075, +0.0165], p=0.46 (passes) | +0.0014 [-0.0059, +0.0087], p=0.71 (passes) | -0.0006 [-0.0156, +0.0145], p=0.94 (passes) |
| high-hazard years only, FE (n=630, contrast) | +0.21 [-0.88, +1.30] | +0.10 [-0.35, +0.54] | +0.07 [-0.77, +0.92] |
| excess-moisture lcr, D x H coef (should be 0) | +0.0209 [+0.0041, +0.0377], p=0.015 (**fails**) | +0.0154 [+0.0045, +0.0264], p=0.006 (**fails**) | +0.0250 [+0.0027, +0.0473], p=0.028 (**fails**) |
| lead test: D of window t+1..t+5 added (n=4,333, years <= 2019); Dlead x H | +0.031 [-0.038, +0.100], p=0.38 (passes) | -0.011 [-0.049, +0.026], p=0.56 (passes) | **-0.084 [-0.149, -0.018], p=0.012 (fails)** |
| ... lagged D x H in the same model | +0.020 [-0.034, +0.075] | +0.016 [-0.013, +0.044] | +0.033 [-0.020, +0.086] |
| Cinelli-Hazlett robustness value RV(q=1) of D x H (FE) | 0.041 (RV at alpha 0.05: 0.017) | 0.003 (0.000) | 0.040 (0.017) |
| D x H adjusted for a confounder as strong as H x irrigation (1x) | +0.042 [+0.017, +0.068] (sign holds) | +0.004 [-0.012, +0.020] | -0.023 [-0.059, +0.012] (**loses significance**) |
| ... 3x as strong as H x irrigation | +0.037 [+0.012, +0.063] | +0.017 [+0.001, +0.033] | +0.074 [+0.038, +0.109] (sign flips) |

The excess-moisture placebo fails for all three measures: diversity also "interacts" with hazard for flood/wet losses,
i.e. D x H picks up something about counties rather than drought-specific protection. The Shannon lead test fails:
diversity measured AFTER the loss year predicts drought sensitivity as strongly as diversity before it (the lagged term
loses significance in that model), which is what a stable county trait, not a causal rotation effect, would produce.

### 3.4 Comparison with Bowles et al. (2020)
Bowles et al. 2020 (One Earth 2:284-293): diversified rotations reduced maize yield losses in drought years by 14-90%
across 11 long-term North American trials. Implied by the county FE estimates (positive = loss reduction):
share_3plus, all remaining 2-crop cropland moved to 3+ crops (+0.79): OLS -100% [-163, -37] (an increase), PPML -41%
[-344, +55]; n_crops +1 class: OLS -2% [-47, +43], PPML -4% [-145, +56]; Shannon +0.66 (corn-soy -> 4-crop window):
OLS +96% [+31, +161], PPML +10% [-197, +73]. These extrapolate far beyond the observed within-county range (within SD
0.05 for share_3plus) and are shown only to make the comparison explicit: depending on the measure, the observational
implied effect ranges from harmful to larger than the trial range, and no measure gives a stable estimate.

### 3.5 Verdict (also in `diversity_effect.json` -> `verdict`)
**No robust observational effect.** The primary "how many crops" measure (share_3plus) is wrong-signed within
counties: +10 pp of cropland in 3+ crop rotations goes with +12.6% [+4.6, +20.5] higher corn drought loss cost in
high-hazard years (PPML +4.4% [-9.7, +20.7], not significant). n_crops_5y is null (+0.2% [-4.3, +4.7]). Shannon looks
protective in the linear FE model (-14.5% [-24.4, -4.7] per +0.1) but not in PPML (-1.6% [-17.9, +17.9]); it fails the
lead test and the excess-moisture placebo, loses significance under a confounder as strong as irrigation, and flips
to +32.2% [+20.9, +43.4] when 2012 is added through the contemporaneous window. With 11-16% of diversity variance
within counties and only three real drought years (2021-2023) after 2012, county insurance data cannot confirm or rule
out the trial effect. We do not interpret the wrong sign as causal (diversity is higher in drought-exposed Plains
counties and in places where wheat/sorghum/forage replace corn, and the excess-moisture placebo fails), but the data do
not support a protective effect.

**What the app uses** (`app_effect` in the JSON): `source = "trial_prior_scenario"`, metric share_3plus. Fields moved
from simple to 3+ crop rotations are assumed to lose a fraction r less in drought years, so the county drought-loss
multiplier is m(s) = (1 - r s) / (1 - r s_now). r: est 0.14 (trial lower bound), lo 0 (no effect, consistent with the
county data), hi 0.90 (trial upper bound). Labelled in county_bill.json (`slider_effect`) and meta.json as a scenario,
not an estimate. Regional `diversity_savings_usd` (every county raised to at least the insured-acre-weighted regional
p90 of share_3plus = 0.45, CDL 2019-2023): est $66.9M/yr, lo $0, hi $475M/yr (3.8% of the expected bill at est).

## 4. Drought-bill simulation (`simulate.py`)

**Method.** The selected model is refit on all 2001-2024 rows (2025 provisional excluded). For each county x crop with
2020-2024 liability > 0, the model is applied to each NASA POWER hazard year 1981-2024 while holding today's county
characteristics fixed (credibility factor from 2001-2024, 2020-2024 irrigated insured share, soils, climatology),
giving 44 simulated lcr per county-crop. Dollars: lcr x 2020-2024 mean liability of that crop in that county
(missing years count as zero), summed over crops and divided by 2020-2024 mean principal insured acres -> $/insured
acre (nominal, 2020-2024 price level; `dollar_year` = "2020-2024 nominal"). Expected bill = mean of the 44 years;
1-in-5 = 80th percentile; 1-in-10 = 90th percentile. Because losses are very skewed, the 1-in-5 bill can be below the
expected bill in counties whose mean is driven by one or two extreme years (1988, 2012). Intervals: 5th-95th percentile
over 100 block-bootstrap refits (2001-2024 training years resampled with replacement; the whole two-stage model,
including the credibility factor, is refit each time). Region/state totals use the bootstrap draws of the totals
(not sums of county bounds). 640 counties have a bill (27 of the 667 have no 2020-2024 principal-crop liability).

**Taxpayer share** = federal premium subsidy / total premium (principal crops, 2020-2024) x expected bill. Actuarial
approximation: RMA sets premiums to cover expected indemnity (target loss ratio ~1.0), so the federal subsidy pays
that share of expected losses. It excludes A&O delivery reimbursements and underwriting gains/losses (both add to the
taxpayer cost) and state subsidies. Region subsidy share = 0.623.

**In-sample calibration** (model fit on 2001-2024, so not a test): simulated region total averaged over hazard years
2001-2024 = $2.02B/yr vs actual lcr x 2020-2024 liability = $1.87B/yr (+8%); 2012 hazard: $12.2B vs $10.7B; 2022:
$2.93B vs $3.19B; 2023: $2.95B vs $3.44B. The highest simulated years are 2012 ($12.2B) and 1988 ($11.4B).

**Results (`regional_summary.json`):**

| area | insured acres (2020-24) | expected bill /yr | taxpayer share /yr | $/insured ac | 2022 actual | 2023 actual | 2001-24 mean actual (nominal) |
|---|---|---|---|---|---|---|---|
| **Region** | 114.5M | **$1.78B [1.55, 1.92]** | **$1.11B [0.97, 1.19]** | 15.58 | $3.74B | $4.17B | $1.27B |
| IA | 21.8M | $236M [186, 281] | $128M | 10.82 | $257M | $716M | $198M |
| NE | 15.5M | $228M [184, 258] | $136M | 14.68 | $930M | $644M | $170M |
| KS | 19.0M | $457M [385, 500] | $288M | 24.09 | $1,560M | $1,384M | $349M |
| MO | 9.1M | $166M [137, 179] | $110M | 18.31 | $180M | $311M | $107M |
| IL | 19.8M | $252M [172, 315] | $148M | 12.76 | $25M | $148M | $166M |
| SD | 13.0M | $307M [251, 340] | $216M | 23.64 | $654M | $319M | $172M |
| MN | 16.4M | $139M [107, 165] | $86M | 8.46 | $131M | $648M | $109M |

The 2001-2024 mean actual is at historical liability (lower prices before 2007); the expected bill is at 2020-2024
liability, which is why it is higher. Region expected bill: $1.78B/yr, of which taxpayers pay about $1.11B/yr (62%).

<!-- FUTURE_START -->
### 4.1 2045 bill (NEX-GDDP-CMIP6 delta method)
**Inputs.** `cmip6_deltas.parquet` (sat module): per county x GCM x scenario, changes 2035-2054 vs 1995-2014
(10 sampled years per period) in JJA and monthly (Jun/Jul/Aug) precipitation (%), Tmax and Tmin (C), EDD30, VPD
(VPD is NaN in this build: no hurs). GCMs available when this was run: 3 (ACCESS-CM2, GFDL-ESM4, MPI-ESM1-2-HR) (the sat module was still fetching
the others; re-run `model/simulate.py --future-only && model/export_web.py` when more land — `regional_summary.json`
is then authoritative over the table below).

**Delta method** (`hazard_features.perturb_county_season`): monthly Jun/Jul/Aug precipitation sums x (1 + monthly
delta) (exact for a multiplicative delta); May has no CMIP6 delta here, so May precipitation is unchanged; daily
POWER Tmax/Tmin shifted by the monthly deltas and EDD30 recomputed from the shifted daily values (keeps the daily
distribution); mean Tmax shifted by the JJA delta (May-June Tmax by the June delta); VPD scaled assuming constant
relative humidity (es of shifted Tmax/Tmin over es of observed); root-zone wetness (GWETROOT JJA, Jul-Aug, May-Jun)
shifted with a within-cell OLS emulator fitted to NASA POWER 1981-2024 (gwetroot_jja = +0.067 x May-Jun precip
fraction anomaly + 0.037 x JJA precip fraction anomaly - 0.0124 per C of Tmax anomaly; within R2 0.62; Jul-Aug R2
0.62; May-Jun R2 0.47). All features are re-standardised against the OBSERVED 1991-2020 climatology, then the same
bootstrap models (point fit + 30 bootstrap refits) are rerun on the 44 perturbed years.
est = median over GCMs of the point-model expected bill; lo/hi = 5th-95th percentile over GCM x bootstrap draws;
change % uses the historical bill of the same bootstrap model.

Consistency check: the EDD increase recomputed from shifted POWER daily data averages +61 degC-day (ACCESS-CM2
ssp245) vs the GCM-native d_edd30_jja of +75 (county correlation 0.89): the delta method gives ~20% less extra heat
than the GCMs' own hotter tails. Mean feature shifts over counties (perturbed minus observed, 1981-2024):
ACCESS-CM2 ssp245: hazard_z +1.18, EDD30 +60.8 degC-day, SPI -0.06, GWETROOT -0.040, VPD +0.24 kPa; ACCESS-CM2 ssp585: hazard_z +0.65, EDD30 +39.3 degC-day, SPI +0.28, GWETROOT -0.024, VPD +0.18 kPa; GFDL-ESM4 ssp245: hazard_z +0.26, EDD30 +25.0 degC-day, SPI +0.41, GWETROOT -0.016, VPD +0.12 kPa; GFDL-ESM4 ssp585: hazard_z +0.43, EDD30 +27.6 degC-day, SPI +0.16, GWETROOT -0.024, VPD +0.13 kPa; MPI-ESM1-2-HR ssp245: hazard_z +0.13, EDD30 +11.9 degC-day, SPI +0.17, GWETROOT -0.004, VPD +0.06 kPa; MPI-ESM1-2-HR ssp585: hazard_z +0.52, EDD30 +25.9 degC-day, SPI -0.08, GWETROOT -0.024, VPD +0.12 kPa.

| area | expected bill today | 2045 ssp245 | change ssp245 [5-95%] | 2045 ssp585 | change ssp585 [5-95%] | change by GCM (point model) |
|---|---|---|---|---|---|---|
| **Region** | $1,780M | $3,180M | +78% [+18, +303] | $3,760M | +111% [+80, +156] | ssp245: ACCESS-CM2 +284%, GFDL-ESM4 +78%, MPI-ESM1-2-HR +26%; ssp585: ACCESS-CM2 +146%, GFDL-ESM4 +110%, MPI-ESM1-2-HR +111% |
| IA | $236M | $373M | +58% [+16, +372] | $449M | +90% [+56, +169] | ssp245: ACCESS-CM2 +352%, GFDL-ESM4 +58%, MPI-ESM1-2-HR +20%; ssp585: ACCESS-CM2 +156%, GFDL-ESM4 +90%, MPI-ESM1-2-HR +70% |
| NE | $228M | $585M | +156% [+30, +311] | $650M | +185% [+112, +220] | ssp245: ACCESS-CM2 +297%, GFDL-ESM4 +156%, MPI-ESM1-2-HR +44%; ssp585: ACCESS-CM2 +159%, GFDL-ESM4 +198%, MPI-ESM1-2-HR +185% |
| KS | $457M | $1,020M | +124% [+6, +182] | $1,210M | +165% [+93, +190] | ssp245: ACCESS-CM2 +162%, GFDL-ESM4 +124%, MPI-ESM1-2-HR +15%; ssp585: ACCESS-CM2 +122%, GFDL-ESM4 +165%, MPI-ESM1-2-HR +173% |
| MO | $166M | $272M | +64% [+8, +192] | $295M | +78% [+56, +111] | ssp245: ACCESS-CM2 +155%, GFDL-ESM4 +64%, MPI-ESM1-2-HR +14%; ssp585: ACCESS-CM2 +78%, GFDL-ESM4 +88%, MPI-ESM1-2-HR +71% |
| IL | $252M | $367M | +46% [+2, +270] | $389M | +54% [+31, +126] | ssp245: ACCESS-CM2 +233%, GFDL-ESM4 +46%, MPI-ESM1-2-HR +8%; ssp585: ACCESS-CM2 +100%, GFDL-ESM4 +44%, MPI-ESM1-2-HR +54% |
| SD | $307M | $481M | +57% [+19, +472] | $569M | +86% [+51, +210] | ssp245: ACCESS-CM2 +454%, GFDL-ESM4 +34%, MPI-ESM1-2-HR +57%; ssp585: ACCESS-CM2 +198%, GFDL-ESM4 +74%, MPI-ESM1-2-HR +86% |
| MN | $139M | $171M | +23% [+3, +452] | $224M | +61% [+41, +247] | ssp245: ACCESS-CM2 +419%, GFDL-ESM4 +8%, MPI-ESM1-2-HR +23%; ssp585: ACCESS-CM2 +228%, GFDL-ESM4 +47%, MPI-ESM1-2-HR +61% |

**Reading.** With 3 GCM(s) the regional expected drought bill rises by +78% (ssp245; range
+18 to +303%) and +111% (ssp585; +80 to +156%) around 2045, at today's insured acres and
2020-2024 liability. Region expected bill: $3.18B/yr (ssp245) and $3.76B/yr (ssp585) vs $1.78B today.
The rise comes mainly from more extreme heat (EDD) in every year; projected JJA precipitation changes are small
(GCM-mean -4% to +11%). Caveats: (1) the GCM spread is the dominant uncertainty and the ensemble is small; ACCESS-CM2 is
a high-climate-sensitivity model; ssp585 can come out below ssp245 for a GCM because each period is only 10 sampled
years (internal variability); (2) the loss model learned heat effects mostly from years when heat came with dry soils,
so adding heat with little drying may overstate losses; tree models also cap responses at the most extreme hazard seen
in 1981-2024; (3) no adaptation, no change in insured acreage, prices, coverage or technology; (4) year-to-year
variability is held at 1981-2024's (delta method).
<!-- FUTURE_END -->

## 5. Outputs

### `model/outputs/`
| file | content |
|---|---|
| panel.parquet | modelling panel (section 1) |
| hazard_features.parquet | county x year 1981-2025 NASA POWER features (667 x 45 = 30,015 rows) |
| hazard_features_check.json | reproduction check + wetness emulator coefficients |
| power_base_stats.pkl | per-cell 1991-2020 base statistics + emulator (used to standardise CMIP6-perturbed weather) |
| cv_results.json, cv_oof/*.parquet | every CV candidate's metrics and out-of-fold predictions |
| model_config.json | selected model + baselines |
| validation.json | full test results: metrics, CIs, by year/state, per-year metrics, coverage, CV table, ablations |
| hindcast_county.parquet | fips, state_abbr, year (2021-2024), insured_acres, liability_usd, actual_usd, pred_usd, lo, hi, pred_usd_baseline_mean, pred_usd_baseline_hazard_only (principal crops, nominal $) |
| hindcast_crop.parquet | fips, crop, year, liability_usd, insured_acres, indem_drought_usd, pred (lcr) |
| hindcast_boot.npz | bootstrap test predictions (crop rows) per model |
| ablations.json | section 2.3 |
| diversity_effect.json | section 3: every estimate, CI, n, diagnostics, verdict, app_effect |
| county_sim.parquet | per county: principal_{mean,p80,p90,y2012,y2022,y2023}[_lo,_hi] and corn_* ($/insured ac/yr), principal/corn_2045_{ssp245,ssp585}[_lo,_hi], liab_recent, acres_recent, prem_recent, subs_recent, liab_per_ac, subsidy_share, n_gcms |
| county_sim_hist.parquet | same without the 2045 columns |
| sim_principal_by_year.parquet | fips x y1981..y2024 simulated principal $/insured acre (point model) |
| sim_totals_boot.parquet | boot (0 = point fit), state, expected_usd |
| sim_future.parquet | fips, gcm, scenario, boot (0..30), principal_mean, principal_p90, corn_mean ($/ac), hist_principal_mean, hist_corn_mean (same bootstrap model) |
| sim_future_features.parquet | county mean of perturbed hazard_z, edd30_jja, spi_jja, gwetroot_jja, vpd per gcm x scenario |
| sim_state.pkl.gz | fitted bootstrap models + simulation frame for `--future-only` (~40 MB, regenerable: suggest gitignore, as for hindcast_boot.npz and cv_oof*) |
| sim_county_crop.parquet | per-crop simulated distributions for the strategy engine (schema below) |

### `sim_county_crop.parquet` (for the strategy engine)
94,908 rows = (county x crop with 2020-2024 liability > 0) x 44 hazard years 1981-2024. County-crops: corn 639,
soybeans 626, wheat 546, sorghum 346.

| column | meaning |
|---|---|
| fips, crop, hazard_year | key; hazard_year = the NASA POWER weather year applied to today's county |
| state_abbr | state |
| lcr_sim | simulated drought loss cost ratio (indemnity / liability), point model |
| lcr_sim_lo, lcr_sim_hi | 5th / 95th percentile over 100 bootstrap refits |
| usd_per_ac_sim | lcr_sim x liab_per_ac_recent ($/insured acre of that crop, nominal 2020-2024) |
| liab_per_ac_recent, liab_recent, acres_recent | 2020-2024 mean liability/acre, liability, insured acres of that crop |
| n_years_hist | years 2001-2024 with >= 1,000 insured acres of the crop in the county |
| enough_history | n_years_hist >= 5 (corn 628, soybeans 604, wheat 414, sorghum 193 county-crops). Use only these for crop-swap cards; others are extrapolated from state/region patterns via the static features and a credibility factor near 1 |

Expected crop bill = mean of usd_per_ac_sim over hazard years; 1-in-10 = 90th percentile.
Caveat: a crop's lcr is per dollar of that crop's liability; comparing crops needs liability/acre (wheat and sorghum
have much lower liability per acre than corn), and a swap changes revenue too.

### `web/data/`
- `hindcast.json`: {train_years, test_years, metrics_units, metrics{model, baseline_mean, baseline_hazard_only:
  {n, mae, rmse, r2, spearman, total_bias_pct}}, metrics_ci, by_year (model), by_year_models (all three), by_state
  [{state, year, pred_total_usd, lo, hi, actual_total_usd}], notes, mock:false}.
- `county_bill.json`: contract schema; plus per county `corn` {expected_bill, bill_1in10, bill_2045}, diversity
  {now, p90_region, n_crops_now, share_cont_corn, shannon_now}, slider {div_values, metric, hazard_year,
  bill_2022_style, lo, hi, bill_2012_style (same multipliers applied to the county's simulated 2012-hazard bill)}; top level `diversity_metric`, `slider_effect`, `notes`. $/ac rounded to 3 significant
  digits. `diversity.now` is **share_3plus** (share of cropland in 3+ crop rotations, CDL window 2019-2023, per the CDL
  module's advice that the 2024 hay->grass relabel inflates the 2020-2024 window), not Shannon.
  `aws_mm` = aws0_150_mm. `actual` = that year's RMA drought indemnity per insured acre (nominal).
- `regional_summary.json`: {units, dollar_year, region{name, insured_acres, expected_bill_usd, taxpayer_share_usd,
  taxpayer_fraction, actual_2022_usd, actual_2023_usd, actual_2012_usd, actual_mean_2001_2024_usd_nominal,
  expected_bill_per_insured_acre, diversity_savings_usd, bill_2045_usd, change_2045_pct (percent),
  change_2045_pct_by_gcm}, states{...same}, notes}.
- `meta.json`: generated_at, region, data_sources (nasa flags), caveats, validation metrics.

## 6. Limitations
- **Under-prediction of the 2022-2023 totals by ~45-50%** (section 2.2); intervals are parameter intervals with 39%
  county coverage. The simulated bill is fit on 2001-2024 (including 2022-2023), so it is less affected, but a bill
  driven mainly by May-Aug weather will understate multi-season droughts and winter-wheat drought.
- Hazard is JJA/May-June NASA POWER at one ~50 km MERRA-2 cell per county (no fall/winter/spring antecedent features,
  no September). Precipitation is MERRA-2 bias-corrected (POWER), not IMERG (host unreachable).
- Drought = RMA cause code 11 only; heat/hot wind (12, 62) and area-plan/endorsement indemnity (code 55, e.g.
  SCO/ECO) are excluded, so the bill is a lower bound on weather-driven insured losses.
- Holding "today's county" fixed ignores trends in coverage level, unit structure, insurance plans and technology;
  the credibility factor averages 2001-2024 behaviour.
- Nominal dollars at 2020-2024 liability/acre (high-price years). Taxpayer share is an approximation.
- Tree models cannot extrapolate: hazard combinations beyond those seen in 1981-2024 are capped at the most extreme
  observed response (relevant for 2045).
- Rotation diversity: no robust observational effect (section 3); the slider/savings use a labelled trial-based
  scenario.
