# Validation

What we tested, against what, and what the results do and do not show. All numbers come from `web/data/validation.json`
(written by `model/validation.py` and `model/grace_compare.py`), `data/processed/hls_irrigation_metrics.json` and the module notes.
Regenerate with `cd model && python3 run_all.py`.

## 1. Hindcast design

The clock is built from a decline rate fitted to past water levels. The test: hide later years, fit on earlier years only, and predict
what the wells measured afterwards.

| Fold | Training data | Predicted | Role |
|---|---|---|---|
| **2014 fold** (headline) | water years up to 2014; Kalman window 1999-2014; weather climatology up to 2013 | 2015-2026 | Main out-of-time test |
| **2004 fold** | up to 2004 | to 2016 | Stability check in a different decade |

Two designs in each fold:
- **Temporal holdout:** the same wells, later years. Every well with enough training data (n = 695 for the 10-year change in the 2014 fold).
- **Spatial holdout:** 20% of wells per county, chosen at random (seed 7), removed **before** anything is fitted: weather
  coefficients, Kalman settings, pooling and the decade-to-decade term are re-estimated without them. Their decline is then predicted
  by kriging from the other 80% (n = 145).

Baselines the model must beat:
- **No change:** the water level stays where it was in the last training year.
- **Own trend:** each well's own straight-line trend (temporal holdout only).
- **County trend:** the county's average trend.

Leakage checks:
- Weather anomalies use a training-only climatology (fixed in the model fix pass; before the fix the 2014-fold MAE was 6.00 ft, after 6.13 ft).
- Adding random noise (SD 500 ft) to every 2015-2019 water level left all metrics unchanged, so no post-2014 levels reach the fit.

## 2. Results: 10-year water-level change (ft)

MAE = mean absolute error; RMSE = root mean square error (punishes large misses); bias = mean (predicted - observed); negative bias =
predicted more decline than happened. Best value per row in bold.

**2014 fold** (2014 to 2024)

| Design | Model MAE / RMSE / bias | No change | Own trend | County trend | Model 80% interval coverage |
|---|---|---|---|---|---|
| Temporal (n = 695) | **6.13** / 9.98 / -5.10 | 6.25 / **9.58** / +4.83 | 7.42 / 11.99 / -6.66 | 7.80 / 11.10 / -7.00 | 91% |
| Spatial (n = 145) | 6.64 / 10.44 / -5.77 | **5.94 / 9.54** / +4.61 | - | 7.88 / 11.24 / -7.22 | 89% |

**2004 fold** (2004 to 2014)

| Design | Model MAE / RMSE / bias | No change | Own trend | County trend | Model 80% interval coverage |
|---|---|---|---|---|---|
| Temporal (n = 636) | **6.65 / 12.12** / +4.42 | 12.20 / 19.46 / +11.83 | 7.42 / 13.19 / +5.76 | 8.41 / 14.14 / +5.61 | 88% |
| Spatial (n = 131) | **7.60 / 13.30** / +5.42 | 13.21 / 20.26 / +12.98 | - | 9.04 / 14.25 / +6.74 | 87% |

Effect of partial pooling (2014 temporal): MAE 6.13 with pooling vs 6.74 without; RMSE 9.98 vs 11.80.

## 3. Results: water level in each well's latest test year (ft)

| Fold, design | Model MAE / RMSE (80% coverage) | No change | Own trend | County trend |
|---|---|---|---|---|
| 2014 temporal (n = 759) | **6.94 / 11.26** (93%) | 7.48 / 11.39 | 8.38 / 13.65 | 8.90 / 12.85 |
| 2014 spatial (n = 157) | **18.45 / 27.70** (89%) | 20.27 / 29.04 | - | 19.04 / 29.06 |
| 2004 temporal (n = 704) | **7.90 / 14.34** (88%) | 14.29 / 22.28 | 8.82 / 15.80 | 9.86 / 16.10 |
| 2004 spatial (n = 143) | **21.95** / 33.56 (83%) | 26.72 / 39.29 | - | 22.13 / **33.29** |

Spatial level errors are much larger (18-22 ft) because a held-out well's absolute level has to be interpolated from neighbours,
and water-table elevation changes by tens of feet over a few km.

## 4. Reading the hindcast honestly

- **Declines slowed after 2014.** Observed mean 10-year change was -4.8 ft for 2014-2024, against -11.8 ft for 2004-2014. Trained on the
  fast-decline years, the model predicted about -9.9 ft: roughly twice the decline that happened (bias -5.1 ft per decade).
- **In the 2014 fold the model's edge over "no change" is marginal and on MAE only.** Its RMSE is worse (9.98 vs 9.58). For wells it
  never saw, "no change" wins on both MAE and RMSE.
- **In the 2004 fold, when declines sped up, the model roughly halves the error of "no change"** and beats every baseline.
- So the model tracks a steady trend well, but the trend itself shifts from decade to decade by about a third. The clock therefore
  includes a decade-to-decade variability term (`sigma_reg`, about 36% of the rate plus 0.16 ft/yr), and that is why its ranges are wide.
- **The model ranks wells well:** predicted vs observed 10-year change correlates at r = 0.69 (temporal) and 0.76 (spatial) in the 2014 fold.
- **80% intervals contain the truth 83-93% of the time.** They are honest and slightly conservative (too wide rather than too narrow).
- **The 2014 fold is not a fully clean test.** While building, we compared model variants (plain filter vs straight-line fit, 10/16/26-year
  windows, with and without weather adjustment) on both folds and kept the one that was most consistent across both. A 26-year straight-line
  trend was better on the 2014 fold alone and worse on the 2004 fold.

## 5. Saturated thickness vs the published USGS 2009 map

We rebuilt the 2009 saturated thickness with our method (869 wells with a 2009 winter level and a reliable base) and compared it to USGS
SIR 2012-5177 on 10,534 grid cells where the published value is above 10 ft (USGS set thinner cells to 10 ft).

| Method | Median difference | MAE | RMSE | r |
|---|---|---|---|---|
| Thickness kriged from wells (used) | +3.8 ft | 17.7 ft | 25.3 ft | 0.97 |
| Water level kriged, minus base grid | +0.9 ft | 20.8 ft | - | 0.95 |

Median published thickness 74 ft, ours 80 ft. The match is good regionally, but an 18 ft average error matters where the aquifer is thin:
with 40 ft of thickness and a 30 ft threshold, 18 ft is most of the usable water. This is why the clock carries a +/-22 ft base
uncertainty and why thin-aquifer counties show wide ranges.

## 6. Pumping vs decline (water balance)

| Test | Result |
|---|---|
| Across 26 counties, mean annual level change vs mean pumping depth, 1991-2026 | R² = 0.90; slope -4.74 ft per ft of pumping; apparent specific yield 0.21 |
| Combined with the literature prior (Sy 0.10-0.20) | Sy_app = 0.204 (80%: 0.186 to 0.226) |
| Year-to-year, within counties | R² = 0.14 (GMD4 aggregate 0.68, GMD3 0.32, GMD1 0.04) |

The long-term link is strong, so reducing pumping should slow the decline roughly in proportion. Year-to-year fits are weak because dry
years raise pumping and cut recharge at the same time; those slopes are kept as diagnostics only. Sy_app is on a gross-pumping basis
(it absorbs return flow); a true Sy of 0.15 with about 25% return flow would give this value, which is consistent but not proven.

## 7. GRACE vs wells

Well-based storage change = aquifer-weighted mean winter water-level change x specific yield 0.15 (range 0.10-0.20) over the 89% of the
region underlain by the aquifer, in cm of water. GRACE = mean of November-March around each January.

| Series | Correlation with wells (annual) | Correlation of year-to-year changes |
|---|---|---|
| GFZ GRACE/GRACE-FO total water storage, 2003-2026 | 0.86 | 0.49 |
| G3P GRACE-based groundwater, 2003-2023 | 0.80 | - |
| GRACE-DA groundwater percentile | 0.68 | - |

| Trend | Wells | GRACE (GFZ) |
|---|---|---|
| 2003-2026 | -3.96 cm/yr (range -2.64 to -5.28 for Sy 0.10-0.20); -5.38 at Sy_app 0.204 | -0.90 cm/yr (range -0.62 to -1.17) |
| 2018-2026 (GRACE-FO era) | -3.26 cm/yr | -2.19 cm/yr |

- **Timing and direction agree:** the yearly series rise and fall together (r = 0.86); both drop in drought years (GRACE annual
  storage anomaly: 2012 -5.7 cm, 2014 -9.2 cm, 2019 +0.3 cm, 2023 -15.1 cm).
- **Size does not agree:** the long-term well-based loss is about 4 times the GRACE trend (6 times at the water-balance Sy).
  Reported gross pumping, 2.04 million AF/yr (2016-2025), equals 4.2 cm/yr over the region, which supports the well number.
- A likely but **untested** reason is GRACE's ~300 km footprint, which blends this concentrated loss with a larger area. That area also
  includes neighbours losing water, so footprint leakage alone may not explain the gap.
- **Use:** GRACE is an independent check on timing and sign. It is not used to scale the clock.
- The gap narrows after 2018 (-3.3 vs -2.2 cm/yr).

## 8. Satellite irrigation detection (HLS)

Can a satellite tell irrigated from dryland fields? We took HLS (Landsat + Sentinel-2) NDVI during the driest 14-day window of July-August
(found from NASA POWER rain) in Haskell and Finney counties, summers 2022 and 2023 (33 scenes). Labels came from WIMAS: irrigated = an
irrigation well that reported water that year within 800 m; dryland = no well of any kind within 1,600 m. The NDVI threshold was chosen on
a random half and tested on the other half.

| Test set | Threshold | n (irrigated) | Accuracy | Kappa | Median NDVI irrigated vs dryland |
|---|---|---|---|---|---|
| Corn, both counties and years | 0.65 | 299 (151) | **0.92** | **0.83** | 0.85 vs 0.38 |
| Corn 2022 | 0.56 | 149 | 0.91 | 0.82 | |
| Corn 2023 | 0.60 | 150 | 0.92 | 0.84 | |
| All crops pooled | 0.62 | 742 (441) | 0.76 | 0.51 | 0.83 vs 0.46 |

- Dry-spell greenness separates irrigated from dryland **corn** well. Sorghum is the main error: it is planted in June, so its canopy is
  still open in early July, and some "irrigated" sorghum pixels are probably dryland sorghum on the same farm.
- Caveats: labels are distance proxies, not field boundaries; the test set is balanced, so accuracy at real prevalence differs; dryland
  samples are spatially clustered (only 21 distinct 1 km cells per year in Haskell), which flatters the result; thresholds vary by year
  (0.56-0.84), so a single threshold should not be transferred blindly.
- This test is a proof of concept. The clock uses WIMAS-reported irrigated points, not HLS classifications.

## 9. Precipitation: IMERG vs NASA POWER

IMERG daily (served by NASA POWER, 0.1 deg, county-centroid point) vs POWER PRECTOTCORR, 2001-2025, 26 counties:

| Comparison | r |
|---|---|
| Region mean, annual | 0.89 |
| Region mean, April-September | 0.93 |
| County-years | 0.87 (per-county median 0.87, min 0.73) |

IMERG is wetter by +1.15 in/yr (+5.8%) on average, with the largest gaps in recent years (2020 +4.0 in, 2023 +3.8 in, 2024 +7.2 in). The
weather adjustment uses POWER; 2020+ precipitation should be treated as uncertain by several inches. A 4-day check against the Planetary
Computer IMERG V06B Zarr gave r = 0.79 (same storms, different product versions).

## 10. Model choices that affect results

- **Wallace County** is kept in GMD4 (contract county list), although 90% of its WIMAS irrigated acres lie inside the official GMD1
  polygon. Moving it to GMD1 changes GMD1 at 30 ft from 6.7 to 5.4 years and GMD4 from 98.4 to 100+.
- **Thin-aquifer wells excluded from thickness:** wells where the USGS 2009 map shows thin or absent aquifer (65 wells) are used for decline
  rates but not for thickness. This moves Wallace from 14.6 to 3.7 years and Morton from 87 to 94.5; other counties barely change.
- **Monte Carlo:** 10,000 draws per point; spot checks against 200,000 draws agree within about 1.5 years.
- **Zero-shift check:** a 0% strategy shift reproduces every county clock exactly at all three thresholds (`scenario.json: zero_shift_check = passed`).

## 11. What the validation shows and does not show

Shows:
- The decline-rate model predicts 10-year water-level change about as well as, or better than, simple rules, and much better when declines
  accelerate. Its 80% ranges are reliable.
- Our saturated thickness reproduces the published USGS surface regionally (r = 0.97).
- Long-term decline is tightly tied to reported pumping (R² = 0.90), which supports the "pump less, clock slows" logic.
- GRACE independently confirms the timing of storage losses.
- Dry-spell HLS NDVI can map irrigated corn.

Does not show:
- **That the years-left numbers will come true.** No hindcast can test a 30-100 year projection. Ten-year tests show the rate itself shifts
  by about a third between decades.
- **That a strategy change will deliver the computed years gained.** The scenario uses the cross-county pumping-decline relationship; it has
  not been tested on a real before/after case in this project (the Sheridan-6 LEMA is cited as outside evidence, see CLAIMS.md).
- **Field-level accuracy where the aquifer is thin.** Thickness errors of about 18-25 ft dominate there.
- **That GRACE confirms the size of the loss.** It does not; it shows about a quarter of the well-based trend.
- **Income accuracy.** Income estimates were not validated against farm records.
