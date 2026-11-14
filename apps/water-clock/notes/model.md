# Module: model (groundwater state, water balance, validation, rotation engine)

Owner files: `model/*.py`, `web/data/*.json` (all ten contract files), this note. Draft validation numbers are in
`web/data/validation.json`. Rebuild everything (about 25 s, at most 4 BLAS threads):

```
cd apps/water-clock/model && python3 run_all.py
```

Inputs are only the processed files in `data/processed/`. No value is typed in by hand. The only constants are model
settings and literature priors, listed below with citations. Intermediate tables go to `data/raw/model_cache/`, which is
gitignored. They include `fields_full.parquet` (every field with all thresholds and SDs), `grid_full.parquet`,
`well_states.parquet`, `water_balance_county.parquet`, `validation_full.json`, `grace_compare_full.json` and
`model_summary.json`.

| Script | Role |
|---|---|
| `common.py` | Paths, county list, priors with citations, JSON writer, helpers |
| `wells_state.py` | Weather adjustment, local-linear-trend Kalman filter, empirical-Bayes pooling |
| `spatial.py` | Local kriging (ordinary, and universal with a quadratic drift), aquifer-base grid lookup |
| `clock.py` | Field table (WIMAS), interpolation to fields and grid, Monte Carlo years left, county/GMD/region aggregation, USGS 2009 cross-check |
| `water_balance.py` | Pumping vs decline (apparent Sy, pumping-attributable decline), decadal non-stationarity term |
| `validation.py` | Out-of-time hindcasts (2014 and 2004 folds), temporal and spatial holdouts, baselines |
| `grace_compare.py` | Well-based storage anomaly vs GRACE (GFZ total water storage, G3P groundwater, GRACE-DA percentile) |
| `rotation.py`, `strategies_text.py` | Crop water use, climate sensitivity, yields, income, strategy text |
| `run_all.py` | Orchestration; writes `web/data/*.json` and checks that a 0% scenario shift reproduces the clock |

## 1. Well state: decline rates

**Data**
- Annual winter levels: `wells_levels.is_annual` with no outlier flag.
- Wells with `sat_flag` in {ok, thin_or_absent_usgs2009}. The levels are valid for thin wells; only the base is doubtful.
- 26 counties, 63,819 well-years, 3,814 wells.

**Weather adjustment**
- With well fixed effects, I estimate `dh_t = a_i + gP*Panom_{t-1} + gE*ET0anom_{t-1}`.
- Panom and ET0anom are the April-September NASA POWER precipitation and FAO-56 ET0 anomalies (inches) of the preceding season, measured against the county's 1984-2025 mean.
- Clock fit, 1985-2026, 36,201 well-year pairs: gP = +0.076 ft/in (SE 0.008), gE = -0.133 ft/in (SE 0.009).
- The cumulative weather effect is removed before filtering. The slope is therefore a weather-normalised decline rate, and forecasts assume average weather.
- In the hindcast, this adjustment cut the 2014-fold MAE from 9.2 to 7.4 ft compared with the unadjusted filter.

**Local-linear-trend state space** (vectorised Kalman filter, `wells_state.kalman`)
- Model: `y_t = l_t + e_t` (var r), `l_{t+1} = l_t + b_t + eta` (var q_l), `b_{t+1} = b_t + zeta` (var q_s).
- Missing years are skipped. The start is diffuse: level from the first observation, slope prior SD 10 ft/yr.
- The likelihood excludes each well's first two observations.
- (r, q_l, q_s) are shared by all wells and fitted by maximum likelihood (Nelder-Mead on up to 800 wells).

| Setting | Clock fit | Hindcast, 2014 fold |
|---|---|---|
| Window (water years) | 2011-2026 (15 years of change) | 1999-2014 |
| Wells | 929 (≥5 values in the window, span ≥8 yr, last value ≥2018) | |
| r (ft²) | 0.045 | 1.09 |
| q_l (ft²) | 6.77 | 4.85 |
| q_s (ft²) | ≈0 | 0.053 |

- In the clock window the MLE picks a random walk with drift: level shocks persist, as expected when a dry year's extra pumping removes water for good.
- Slope SE per well is about 0.7 ft/yr. It is dominated by shocks that wells share, which is why pooling and kriging do not treat it as independent noise.

**Partial pooling** (two-level empirical Bayes, DerSimonian-Laird)
- Wells are pooled within counties, with a shared within-county SD tau_w = 0.60 ft/yr.
- Counties are pooled within GMDs; tau_c is about 0.32 (GMD4), 0.64 (GMD3) and 0 (GMD1).
- The posterior well slope `b_post` and the county mean ± SE (`se_post`, 0.11-0.33 ft/yr) are used in the temporal hindcast and the county decline intervals.
- Pooling improved the 2014 fold: 10-yr change MAE 6.0 vs 6.7 ft unpooled.

## 2. Spatial interpolation and saturated thickness

**Decline rate**
- Ordinary kriging of the 929 weather-adjusted Kalman slopes.
- Local: 16 nearest wells, exponential covariance, batched solves.
- Fitted variogram: nugget 0.25 (ft/yr)², partial sill 0.96, range 39 km.
- The nugget is treated as estimation noise and left out at the target.
- Kriging SD is about 0.6 ft/yr away from wells and lower close to them.

**Saturated thickness**
- At every well with a winter level in 2024-2026 (982 wells), the level is projected to Jan 2026 with the kriged decline.
- Thickness at the well = projected level minus that well's base: its KGS depth-to-bedrock pick if it has one, else the USGS OFR 98-393 base plus the IDW-interpolated KGS residual (wells module).
- These well values are kriged with a quadratic drift in x/y (universal kriging): nugget 392 ft², partial sill 3,671 ft², range 23 km.
- Forming thickness at the wells removes the eastward slope that the water table and the base share.
- Target SD = sqrt(kriging variance without nugget + 22²), where 22 ft is the aquifer-base uncertainty (`PRIORS['base_sd_ft']`: pick-residual MAD 22.6 ft and well-level MAE 21.9 ft from notes/wells.md).
- Cells and fields where the USGS 2009 raster shows no aquifer are left null (326 of 13,233 fields).
- Thickness is clipped at 0.

**Cross-check against the published USGS 2009 surface** (SIR 2012-5177)
- I rebuilt 2009 with the same method from 942 wells with a 2009 winter level and compared on 10,534 grid cells where the published value is above 10 ft. (USGS set cells of 10 ft or less to 10 ft.)

| Method | Median diff (ft) | MAE (ft) | RMSE (ft) | r |
|---|---|---|---|---|
| Thickness kriged from wells (used) | +2.8 | 17.4 | 25.0 | 0.966 |
| Water level kriged, then minus base grid | | 20.3 | | 0.952 |

- The first method fits the published surface better, so it is the one used.
- Median water-level change 2009 → 2026 across aquifer cells is -6.6 ft.

**Targets**
- **Fields:** 13,233 WIMAS groundwater irrigation points of diversion with reported use > 0 in 2021-2025.
  - acres and af_yr are 2021-2025 means.
  - crop is the most frequent single crop reported in WIMAS, else the CDL 250 m mode for 2020-2024.
- **Grid:** 15,385 cells of 0.02 deg inside the 26 counties, the same grid as `aquifer_base.json`.

## 3. Years left (Monte Carlo)

At every field and grid cell, I draw 2,000 times, independently:
- **Saturated thickness:** S ~ N(sat, sat_sd).
- **Decline:** D ~ N(decl, sqrt(kriging var + sigma_reg(decl)²)).

**Decadal non-stationarity, `sigma_reg`**
- `sigma_reg = sqrt(floor² + (k*decl)²)`, with floor = 0.16 ft/yr and k = 0.36.
- I estimated it from how much weather-adjusted county mean decline rates differ between 1996-2006, 2006-2016 and 2016-2026.
  - Low-decline counties (|rate| < 0.5) give the floor.
  - Higher-decline counties give the relative term k.
- Rates change a lot by decade. Finney, for example, went -1.9, -3.6 and -1.5 ft/yr. This term covers that.

**Years at threshold T** (15, 30, 50 ft)
- Years = (S - T)/D.
- If D ≤ 0 (flat or rising), years = 100 (shown as ">100").
- If S ≤ T, years = 0 (already below).
- All values are capped at 100. p10/p50/p90 are taken over the draws.

**Aggregation**
- County, GMD and region values are the acre-weighted median, over their irrigated points (weights = reported acres), of each point's p10, p50 and p90.
- `sat_thick_ft` p10/p50/p90 is the acre-weighted spread across the county's points.
- `decline_ft_yr.est` is the acre-weighted mean of point declines. Its interval is est ± 1.28 × sqrt(county EB SE² + sigma_reg²).
- In four counties (Decatur, Logan, Gove, Graham) the mean is ≤ 0.05 ft/yr. There, est is the mean over declining points and `decline_note` says so.

**Literature priors** (`common.PRIORS`)
- **Specific yield Sy:** 0.15, range 0.10-0.20. USGS uses about 15% as an area-weighted average for High Plains storage change (McGuire, USGS SIR 2017-5040 and earlier reports, from Gutentag et al. 1984, USGS PP 1400-B). The exact page was not re-checked.
- **Recharge:** 0.1-1.5 in/yr, the range from CONTRACTS.md. Used only as a plausibility check.

Sy and recharge do not enter the baseline clock directly, because the decline is observed. They enter the water balance (section 4) and the GRACE comparison.

## 4. Water balance: pumping → decline

**Per-county time series** (Butler et al. 2016 GRL approach, doi:10.1002/2016GL067879, citation details unverified)
- I regressed the annual change in county mean winter level, dWL_t (from wells measured in consecutive years), on reported groundwater pumping in t-1, divided by the county's aquifer area.
- This works for GMD4 as an aggregate (R² 0.68) but poorly in GMD3 (0.32) and GMD1 (0.04).
- The implied apparent Sy is implausible: 0.01-0.4 by county, 0.04 for GMD4.
- The reason is that year-to-year pumping mostly tracks weather. Dry years have both high pumping and low recharge, and the county footprint dilutes local drawdown. These slopes are kept only as diagnostics.
- The pooled within-county estimate is Sy_app 0.139 with R² 0.14.

**Long-term cross-section** (used)
- Across the 26 counties, I regressed mean annual level change against mean pumping depth (AF/acre of aquifer area) for 1991-2026: slope -4.74 ft per ft of pumping, R² = 0.90, intercept +0.036 ft/yr.
- Apparent Sy = 0.211. The jackknife SE on 1/Sy is 0.37.
- I combined this with the prior on 1/Sy (Sy 0.10-0.20 taken as a 95% range): posterior **Sy_app = 0.204 (80%: 0.186-0.226)**, with 92% of the weight on the data.
- Sy_app is on a gross-pumping basis, so it absorbs irrigation return flow. A true Sy of 0.15 with about 25% return flow would give this value. That is consistent, but not proven.
- The intercept implies near-zero net inflow (about 0.1 in/yr). That is at the low end of the recharge prior.

**Outputs per county**
- `decline_from_pumping_ft_yr = (1/Sy_app) × Q_recent / A_aq`, where Q_recent is WIMAS groundwater irrigation, mean 2016-2025. Finney: 1.80 ft/yr out of an observed 2.35.
- `ft_per_af_ac = (1/Sy_app) × irrigated_acres / A_aq`.
- `irrigated_acres` = WIMAS groundwater acres (`irr_acres_gw`, mean 2021-2025). These are about 1.4x the Census of Agriculture irrigated land, because several points can report the same field. They are used because they pair with WIMAS AF/acre (notes/pumping.md). Census 2022 values are shown alongside in county_clocks (`irrigated_acres_census_2022`, `irrigated_corn_acres_census_2022`).

**Scenario formula** (`scenario.json`, matches `web/js/scenario.js countyShift`)
- `saved_af = X × irrigated_corn_acres × (net_S0 - net_Sk)/12`
- `new_decline = decline - decline_from_pumping × saved_af / pumping_af_yr`
- `years = sat_avail_ft[T] / decline`, capped at 100.
- `sat_avail_ft[T] = years_p50[T] × decline_ft_yr.est`. The usable thickness is the effective value consistent with the county clock, so a 0% shift reproduces the clock exactly. `run_all.py` checks this for every county and threshold (zero_shift_check = passed).
- `irrigated_corn_acres` = WIMAS groundwater acres × corn share. The corn share is the acre-weighted fraction of 2020-2024 years in which each active point's CDL 250 m mode is corn. Finney: 65.6k ac (34%), against 53.7k in Census 2022, which was a drought year.

## 5. Validation (draft numbers in `web/data/validation.json`)

**Design**
- **2014 fold (headline):** train on water years ≤ 2014. The Kalman window is 1999-2014; weather coefficients and the regime term are estimated only from data up to 2014. Predict 2015-2026.
- **2004 fold (stability check):** train ≤ 2004, predict to 2016.
- **Temporal holdout:** every well with enough training data.
- **Spatial holdout:** 20% of wells per county, random (seed 7), predicted by kriging from the other 80%.

**Results, 10-yr change** (ft, 2014 → 2024 where both observed)

| Fold, design | Model MAE (80% cover) | No change | Own trend | County trend |
|---|---|---|---|---|
| 2014 temporal (n=695) | **6.0** (91%) | 6.3 | 7.4 | 7.8 |
| 2014 spatial (n=145) | 6.4 (89%) | **5.9** | – | 7.9 |
| 2004 temporal (n=636) | **6.5** (89%) | 12.2 | 7.4 | 8.4 |
| 2004 spatial (n=131) | **7.4** (88%) | 13.2 | – | 9.0 |

**Results, level in each well's latest target year**

| Fold, design | Model MAE (80% cover) | No change | Own trend | County trend |
|---|---|---|---|---|
| 2014 temporal | **6.8** (93%) | 7.5 | 8.4 | 8.9 |
| 2014 spatial | **18.3** (89%) | 20.3 | – | 19.0 |
| 2004 temporal | **7.7** (88%) | 14.3 | 8.8 | 9.9 |
| 2004 spatial | **21.7** (83%) | 26.7 | – | 22.1 |

**Reading**
- **Declines slowed after 2014.** Mean observed 10-yr change was -4.8 ft, against -11.8 ft in 2004-2014. The trained model over-predicts decline by about 5 ft per decade in the 2014 fold.
- **No-change wins one case.** It beats the model on the 2014 spatial 10-yr change. It loses everywhere in the 2004 fold, where declines accelerated.
- **Intervals are slightly conservative:** 80% intervals cover 83-93%.
- **Correlation:** predicted vs observed 10-yr change correlates at r = 0.69 (temporal) and 0.77 (spatial) in the 2014 fold.
- **The 2014 fold is not a fully clean test.** During development I compared model variants on both folds: plain filter vs OLS, windows of 10, 16 and 26 years, with and without the weather adjustment. The 16-year weather-adjusted filter was the most consistent across both folds.
  - A 26-year OLS trend was better on the 2014 fold alone: level MAE about 6.2-6.4 vs 7.3-7.5 ft in that exploratory unpooled comparison. It was worse on the 2004 fold.

## 6. GRACE vs wells

**Wells series**
- Aquifer-area-weighted mean annual winter-level change, chained from county means (counties with ≥3 well pairs).
- Multiplied by Sy 0.15 (range 0.10-0.20) and by the 89% of the region area underlain by the aquifer (cells where the USGS 2009 raster has data).
- Gives cm of water over the region.

**GRACE series:** mean of November-March around each January campaign.

| Series | Annual correlation with wells | Year-to-year changes | Years |
|---|---|---|---|
| GFZ total water storage | 0.86 | 0.49 | 2003-2026 |
| G3P groundwater | 0.80 | 0.60 | 2003-2023 |
| GRACE-DA groundwater percentile | 0.68 | 0.60 | |

**Trends**

| Period | Wells | GFZ GRACE |
|---|---|---|
| 2003-2026 | -3.96 cm/yr (Sy range: -2.64 to -5.28) | -0.90 ± 0.22 cm/yr |
| 2018-2026 (GRACE-FO) | -3.26 cm/yr | -2.19 cm/yr |

- GRACE agrees with the wells on timing and sign, including the drought drawdowns. But its long-term trend is about 4 times smaller.
- Reported gross pumping, 2.04 MAF/yr in 2016-2025, equals 4.2 cm/yr over the region. Net depletion is somewhat smaller but of the same order as the wells.
- My explanation is that GRACE's ~300 km footprint spreads a concentrated loss over a larger, partly non-irrigated area (leakage). The implied Sy would be about 0.03, far below any plausible value.
- GRACE is therefore used as an independent consistency check, not to scale the clock. The contract's "fuse" option was not used.

## 7. Rotation engine (`strategies.json`)

**Water use (in/acre/yr)**
- WIMAS application depth on single-crop irrigated points, county-year AF/acre × 12.
- County median 2011-2025 when a county has at least 8 years with ≥300 acres; otherwise the GMD acre-weighted value.
- Region medians: corn 14.6 (year range 12.6-18.9), soybeans 13.8, sorghum 10.3, cotton 10.1, wheat 8.9, alfalfa 19.1.
- **MODIS cross-check** (pure-crop cells, 2008-2024): corn minus sorghum 1.1 in, corn minus wheat 2.3 in. The ordering is the same as WIMAS, but MODIS absolute ET is low for irrigated land, so it is used only as a relative check.
- **Climate sensitivity of applied water** (WIMAS county-year panel 1990-2025, county fixed effects + trend):
  - all crops: 0.36 in per in of April-September ET0 and -0.095 in per in of rain, within-R² 0.58;
  - corn: 0.45 and -0.083;
  - trend -0.13 in/yr (all crops).

**Strategies**

| ID | Strategy | Water rule |
|---|---|---|
| S0 | Continuous irrigated corn | WIMAS corn depth |
| S1 | Corn-wheat-sorghum, limited irrigation | Corn capped at 11 in, the Sheridan-6 LEMA allocation of 55 in over 5 years. Its yield is interpolated linearly between NASS irrigated and dryland, which is conservative. |
| S2 | Dryland wheat-sorghum-fallow | No irrigation. Wheat after fallow, dryland sorghum; the fallow year has 0 income and 0 cost. |
| S3 | Irrigated grain sorghum | WIMAS sorghum depth |
| S4 | Irrigated cotton | Only in the 7 counties where WIMAS reports cotton in ≥5 years since 2011. Income uses the state cotton yield. |

**Income** (USD/acre/yr, return over ERS Prairie Gateway operating costs)
- For each year 2016-2025: county yield × Kansas marketing-year price − operating cost of the same year.
- est = median over years; lo/hi = 10th/90th percentile.
- Practice yield = county all-practice yield × the county's 2000-2018 median NASS practice/all ratio. The state ratio is used if the county has fewer than 3 years.
- Missing county all-practice yields = state yield × county/state ratio.
- Region values weight counties by irrigated corn acres.

**Region results**

| Strategy | Water (in/acre) | Pumping vs S0 | Income ($/acre) |
|---|---|---|---|
| S0 | 14.8 (12.6-18.9) | 0 | 366 (265-742) |
| S1 | 10.0 | -32% | 236 |
| S2 | 0 | -100% | 53 |
| S3 | 10.2 | -31% | 297 |
| S4 | 9.9 | -40% | 253 |

**Evidence entries**
- Every number quoted comes from the processed data: WIMAS, NASS CV and ratio statistics, MODIS, and the Sheridan County before/during-LEMA reported use (-13.7% in 2013-2017 vs 2008-2012, Thomas County -3.7%).
- Literature: Steward et al. 2013 PNAS (doi:10.1073/pnas.1220351110) for the 69%-in-50-years projection, and Deines et al. 2019 ERL for the LEMA response. The Deines details are marked unverified in the card text because the paper could not be opened from this container.

## 8. Climate 2045 (`climate.json`)

**Method**
- Delta method from `cmip6_2045.json`, 5 GCMs. The April-September PM ET0 % change is applied to each county's POWER 1995-2014 April-September ET0.
- Extra applied water = 0.36 × ΔET0 − 0.095 × ΔP (all crops). This raises the decline by ft_per_af_ac × extra/12. The clock is recomputed at 30 ft.
- Range = min-max over the GCMs. Recharge changes are not modelled.

**Results**

| | ssp245 | ssp585 |
|---|---|---|
| ET0 change | +5.9% (2.8-10.6) | +8.3% |
| Extra irrigation on corn | +1.2 in/acre (0.5-2.3) | +1.8 in/acre (1.4-2.1) |
| Region clock shift | -4.2 years (-7.5 to -1.7) | -6.2 years (-7.4 to -4.8) |

## 9. Headline numbers (30 ft threshold)

**Region** (12,907 groundwater-irrigated points inside the aquifer)
- **67 years** (p10-p90: 24 to 100+).
- Saturated thickness p50 104 ft; decline 1.34 ft/yr.
- 17% of irrigated acres have fewer than 25 years.

**By GMD**

| GMD | Years left p50 | p10-p90 | Saturated thickness p50 | Decline (ft/yr) |
|---|---|---|---|---|
| GMD1 | 5 | 0-100+ | 31 ft (thin aquifer) | 0.26 |
| GMD3 | 67 | 31-100+ | 153 ft | 1.71 |
| GMD4 | 96 | 0-100+ | 71 ft | 0.50 |

**By county** (p50 years; per-county numbers are in `county_clocks.json`)

| Years left (p50) | Counties |
|---|---|
| Under 25 | Wichita 0, Hamilton 1.8, Greeley 6.6, Lane 13.8, Wallace 14.6 |
| 25-50 | Stanton 29, Gray 30, Scott 31, Finney 44 |
| 50-75 | Grant 54, Ford 58, Kearny 68, Haskell 70 |
| 75-100 | Sheridan 81, Sherman 85, Morton 87, Stevens 91, Thomas 91 |
| 100+ | Seward, Meade, Cheyenne, Rawlins, Decatur, Logan, Gove, Graham |

## Caveats and known limits

- **The clock extrapolates the 2011-2026 weather-normalised rate.** The hindcast shows the rate can change by about 35% between decades. This is in the intervals, but not as a scenario of policy change.
- **Thin-aquifer counties** (GMD1, Hamilton, Wallace) show p50 at or near 0 years at 30 ft. Many wells there still pump below 30 ft at reduced capacity, so the 15 ft threshold is more informative there.
- **County aggregation** uses WIMAS points, so it describes irrigated land, not the whole county.
- **Data quality** is "thin" for Hamilton (6 wells with trends) and Logan (11).
- **Income** misses irrigated-specific costs and pumping energy. KSU budgets were blocked; ERS mixes irrigated and dryland.
- **District rows are mislabelled.** In `nass_county.parquet`, the district rows `20D40`/`20D70` are named North Central and Northeast. They are not the West Central and Southwest districts of our counties (ASD 20 and 30), so they were not used as fallbacks. Only county and state rows were used. The econ report's statement that 20D40/20D70 are West Central/Southwest appears to be wrong.
- **Wallace** is kept in GMD4, as in the contract, although 90% of its irrigated acres are inside the GMD1 polygon.
- **`fields.json`** holds all 13,233 points, 0.87 MB. No subsample was needed: web/data totals 1.4 MB.

## Failures

None new. No new hosts were contacted. The model uses only processed files.
