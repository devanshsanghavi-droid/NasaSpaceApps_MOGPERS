# Module `fields_model`: field leak score, HUC-12 hotspot index, river calibration, farmer strategies

Scripts (re-runnable end to end, no network, about 1.5 min in total):
```
python3 model/m05_fields.py       # drainage fit, loads, HUC-12 index, calibration, validation, field scores
python3 model/m06_strategies.py   # strategy cards + per-field Monte Carlo of N kept
```
Every number comes from `data/processed/*`, `docs/facts.json` (read by id at run time) and
`shared/evidence/evidence_priors.json`. Nothing is copied by hand into the code except model settings: thresholds, grids and seeds.

Outputs (model/out/):

| file | content |
|---|---|
| `field_scores.parquet` | 1,769 rows. field_id, huc12, seq, crop_2025, drainage, poorly_share, slope_pct; `lbN_ac_<2016..2025>` (central calibrated leak); `leak_lbN_ac_yr_p10/p50/p90`; `leak_index` (1 = focus-area average); `leak_pctile` (0-100); calendar list columns `cal_*` (12 months); `frac_leak_oct_may`, `frac_leak_apr_jun`; `freq_soy_after_corn_2016_2025`; `hls_fallback_share`; `leak_q200` (200-point quantile function of lb N/ac/yr, input to m06); cover_years_json; ndvi_dates/vals; polygon |
| `huc12_scores.parquet` | 290 HUC-12s. kgN_ha_<year> per row-crop ha, kgN_ha_mean, lbN_ac_mean, contrib_t_mean, share_of_basin_leak (2016-2025 mean), share_of_basin_leak_recent (2023-25), share_of_basin_area, leak_index (1 = basin average per row-crop ha), rank (1 = largest share in its basin), bare_days_wet, row_crop_share, poorly_drained_share, modis_filled_share_recent |
| `huc12_props.json` | `{huc12: props}` in the web `huc12.geojson` contract shape, plus extras `lbN_ac_yr`, `share_of_basin_leak_recent`, `n_in_basin` |
| `fields.geojson` | web contract: field_id, huc12, seq, leak_index, leak_pctile, drainage, slope_pct (+ `lbN_ac_yr_p50`) |
| `field_detail.json` | web contract, a single file (4.7 MB, 1,769 fields). Extras: `leak.lbN_ac_yr.mean`, `leak.by_year`, `calendar.leak_share`, `strategies.<S>.*.mean`, `strategies.S1.note` (fields without soybean-after-corn years), `why_field` |
| `strategies.json` | web contract (S0-S3) + `method`, `units`; `cost_usd_ac` carries `basis` and `source`; S3 cost has `verification` |
| `basin_index_check.json` | drainage fit, loads + gap-fill cross-validation, calibration table, validation check, sensitivities, input mtimes |

## 1. Daily drainage driver (per NASA POWER cell)
`D = (liquid rain + snowmelt) × clip((GWETROOT_yesterday − w0)/dw, 0, 1)`, in mm/day.

How the inputs are built:
- **Liquid water:** liquid rain is `PRECTOTCORR − PRECSNOLAND`.
- **Snowmelt:** snowfall fills a snow-water store. The store releases water in proportion to the day's relative loss of snow depth (`SNODP`), so no snow density has to be assumed.
- **Missing snowfall:** from 2026-10-01, PRECSNOLAND is missing; precipitation then counts as snow when T2M ≤ 0 °C.

Why this functional form:
- Tiles and shallow subsurface flow drain only when the root zone is near or above field capacity.
- Rain on dry soil refills storage and produces almost no drainage, which is the 2020-23 drought story.
- A ramp on yesterday's root-zone wetness is the simplest form with that threshold behaviour.

**Fitted, not assumed.** w0, dw and a routing constant (used only for the fit) were grid-searched (896 combinations). The target was **measured monthly runoff** (USGS flow ÷ basin area, 2016-2025, both basins). Result: **w0 = 0.45, dw = 0.10, k = 10 d**.

| Pearson r vs measured runoff | monthly, Raccoon | monthly, Des Moines | annual, Raccoon | annual, Des Moines |
|---|---|---|---|---|
| wet-soil drainage driver | 0.91 | 0.91 | 0.95 | 0.96 |
| all rain + melt (no wetness gate) | 0.64 | 0.70 | 0.85 | 0.92 |

## 2. Measured annual loads (calibration target)
Daily load = no3_mgL × q_cfs × 2.4466.

**Gap filling.** On observed days, ln C is regressed on ln Q, ln Q², two seasonal harmonics and a calendar-year level. The residuals are then interpolated linearly in time between observed days.
- Short gaps therefore behave like interpolating the concentration.
- Long gaps borrow the flow and season signal.
- Missing flow (0.2% of Des Moines days) is interpolated in time.

**Gap-fill uncertainty from cross-validation.** Blocks of 3-90 observed days were hidden and refilled, 120 blocks per length per site. The load-normalised RMSE was 7-34%. Each year's gaps get that error by gap length, combined as a root-sum-square.
- The filled share is 0.1-13% of the annual load, except **Des Moines 2016 (32%: no nitrate data Jan-Mar 2016)**.
- Resulting annual load SD is ≤ 2.5%, except Des Moines 2016 at 7.9%.
- Sensor and rating-curve error are **not** included.

**Share of the river load from row-crop land, s ~ U[0.70, 0.89].**
- Lower bound: CISWRA's "70-80% from agriculture" (lo; secondary).
- Upper bound: INRS nonpoint share 92% (primary), so point sources ≈ 8%. Non-row-crop land (grass, hay, small grain, forest, other; CDL) is assumed to leak ε = 15% of row-crop land per ha (see §3). That gives 0.89 for the Raccoon and 0.90 for the Des Moines; the smaller value is used for both.

**Calibration table.** Values are kg N per row-crop ha per year from row-crop land, central s = 0.80 (lb/ac in brackets). The lo-hi range is ×0.88 to ×1.12.

| year | Raccoon (05484500) | Des Moines (05482000) |
|---|---|---|
| 2016 | 37.1 (33.1) | 43.1 (38.5) |
| 2017 | 21.9 (19.5) | 22.9 (20.4) |
| 2018 | 30.6 (27.3) | 35.0 (31.2) |
| 2019 | 27.3 (24.4) | 24.9 (22.2) |
| 2020 | 10.7 (9.5) | 13.7 (12.3) |
| 2021 | 1.3 (1.2) | 1.5 (1.3) |
| 2022 | 9.0 (8.0) | 7.7 (6.9) |
| 2023 | 3.2 (2.9) | 4.7 (4.2) |
| 2024 | 15.2 (13.6) | 27.7 (24.7) |
| 2025 | 22.3 (19.9) | 23.4 (20.9) |
| mean | 17.9 (15.9) | 20.5 (18.3) |

How to read these numbers:
- These are loads **delivered to the gauges**. Nitrate removed in ditches, streams, and (for the Des Moines) Saylorville Reservoir is not counted. Edge-of-field losses are therefore larger.
- That is consistent with ISU's "about 30 lb N/ac in an average year, 15-50" (facts.json) once the 2020-23 drought years are included.

## 3. Leak index structure (HUC-12 and field)
`daily leak = [bare + ε·(1 − bare)] × D × [1 + (m − 1)·poorly_drained_share]`, calibrated per basin and year.

| factor | value | source / estimation |
|---|---|---|
| bare (HUC-12) | MODIS 13Q1 bare share on row-crop pixels | MODIS living share minus the MODIS−HLS monthly bias (focus area, `hls_vs_modis.json`, interpolated by day of year; May bias 0.34). MODIS is used as a relative index calibrated to HLS, as the orchestrator asked. Gaps > 60 d use HUC-12 day-of-year climatology. The Jul-Nov 2025 PC gap is filled with `cover_hls_huc12_8day.parquet` (HLS quantile-mapped to MODIS, 4,913 rows) |
| bare (field) | 1 − interpolated HLS `live_px_share` (share of the cell's pixels with NDVI ≥ 0.30) | Linear between clear observations, gaps ≤ 120 d (as in the fields module). Longer gaps (winter snow/cloud, and Jan-mid-Feb 2020) fall back to the field's HUC-12 corrected-MODIS bare: 4.1% of field-days. A generic spring spike-scene filter is in the code; it dropped 0 scenes on the fixed data (it dropped 2021-05-09, 2024-05-03 and 2024-05-24 on the old data) |
| ε, leak under living cover | 0.15 | 1 − INRS land-retirement (CRP) reduction 85% (`inrs_crp_pct`) |
| m, tile delivery | U[1, 4] grid, central 2.5 | Poorly and very poorly drained Iowa row-crop land is tile drained. The upper end comes from McIsaac & Hu (2004), cited by David, Drinkwater & McIsaac (2010, JEQ 39:1657): riverine nitrate export = 100% of net N inputs in tiled central Illinois vs 25-37% in the non-tiled south. The 2.7-4× ratio is **our inference**; 1 = no difference. HUC-12 share ranking vs m: Spearman ≥ 0.975 |
| crop year | 1 for corn and soybean | facts.json `isu_lbN_acre_yr` note: "Corn and soybean losses are similar". Not estimated; 20 basin-years cannot separate it |
| weather at a field | bilinear between the 4 surrounding POWER cell centres | Nearest-cell lookup created a false 5× step at the 42.25° N cell edge inside two focus HUC-12s |

**Calibration.** For each basin and year, HUC-12 kg/ha = k × index, so that Σ(kg/ha × row-crop ha) = s × measured load. Fields are then scaled **within their HUC-12**:

field kg/ha(y) = HUC-12 kg/ha(y) × field index(y) / mean field index in that HUC-12(y)

This removes the HLS-vs-MODIS level difference: the HLS index is 1.06-1.36× the MODIS index. For 2016-2019, before HLS, each field's mean 2020-25 relative index is used.

**Field uncertainty (p10/p50/p90).** A Monte Carlo of 4,000 draws over four sources:
- the weather year, uniform 2016-2025;
- s ~ U[0.70, 0.89];
- the gap-fill load error, normal with the basin-year SD;
- m on its grid.

Year-to-year weather dominates. **Median field: p10 0.8, p50 10.5, p90 29.3 lb N/ac/yr; long-run mean 13.2.**

Spread of field p50s:

| percentile | p5 | p25 | median | p75 | p95 |
|---|---|---|---|---|---|
| field p50, lb N/ac/yr | 6.5 | 8.8 | 10.5 | 12.6 | 15.9 |

Poorly drained fields: median p50 is 1.34× that of well and moderately well drained fields.

**Leak calendar (2020-2025 means).**
- `bare_frac`: HLS.
- `rain_mm`, `storm_days` (days ≥ 25 mm) and `wetness` (GWETROOT 0-1): bilinear POWER.
- `leak_risk`: monthly leak index ÷ the field's maximum month.

On the average field, 93% of the leak falls Oct-May and 54% Apr-Jun.

**HUC-12 outputs.**
- `share_of_basin_leak` and `rank` use the 2016-2025 mean (the most climate-representative); 2023-25 values are in `*_recent`.
- `bare_days_wet` = Σ bare share on days with D ≥ 1 mm, Mar-Jun + Sep-Dec, averaged over 2023-2025.

## 4. Validation check: does the uncalibrated index track the river? (`basin_index_check.json`)
The uncalibrated basin index per row-crop ha is compared with measured load per row-crop ha, 2016-2025, n = 20.

| test | Pearson | Spearman |
|---|---|---|
| pooled, both basins | 0.74 (p = 2e-4) | 0.78 |
| Raccoon only (n = 10) | 0.75 | 0.76 |
| Des Moines only (n = 10) | 0.73 | 0.78 |
| drainage only, no cover term | 0.79 | 0.90 |
| POWER precipitation only | 0.83 | 0.83 |
| measured runoff (reference, not a predictor) | 0.87 | 0.93 |

**Honest reading.**
1. Year-to-year load is driven by water. The index tracks it well (r ≈ 0.74), but not better than drainage or rain alone.
2. The satellite cover term does **not** improve interannual tracking.
   - The partial correlation of the cover part with load, controlling for drainage, is −0.40 (p ≈ 0.08).
   - In the ε sensitivity, pooled r rises from 0.71 (ε = 0) to 0.79 (ε = 1, cover ignored).
   - The reason is that interannual MODIS bare-share variation is mostly green-up timing (weather), not management, which the modis module already noted.
   - The cover term is kept on physical and trial grounds (INRS land-retirement efficiency). It matters for the seasonal calendar, for field-to-field differences and for the strategy logic, none of which the 20 basin-years can test.
3. **Per-area ratio Raccoon / Des Moines.** Index 0.73-0.75 vs measured 0.88; the year-to-year correlation of the ratios is r = 0.33 (n = 10, n.s.).
   - The index puts the Des Moines basin relatively higher. It is wetter and more poorly drained (0.52 vs 0.44 poorly drained share).
   - Saylorville Reservoir retention, which the index does not model, would push the measured Des Moines load lower, yet the measured ratio is still higher than the index's. So the index does not capture the between-basin level well; the per-basin calibration absorbs it.
4. **No sub-basin gauge is used, so the within-basin HUC-12 pattern is unvalidated.**
   - In the Raccoon the hotspot ranking follows bare-and-wet days (r = 0.78), which are dominated by POWER (50 km MERRA-2) wetness and rain differences, more than by poorly drained share (r = 0.09).
   - The southern Raccoon HUC-12s (Mosquito, Panther Creek) rank top.
   - The focus area (North Raccoon headwaters) ranks mid-pack: leak_index 0.64-1.06, ranks 16-105 of 105.
   - Present this as "where bare ground meets wet soil", not as measured sub-basin loads.

## 5. Strategies (m06)
Practice efficiencies are read from facts.json. The **Mar 2024 INRS Science Team update** (`inrs_2024_update`) is the primary prior, per the orchestrator's decision; the older table value is shown on the card as context. Reductions are drawn as normal(mean, SD) and clipped to [0, 1]. Each is applied to the field's own leak distribution, `leak_q200`, by Monte Carlo (4,000 draws). N price is U[$0.53 (ISU A1-88 budget), $0.70 (AMS anhydrous high)].

| id | practice | prior (2024 update; older) | what is kept per field | yield risk | cost $/ac (basis) |
|---|---|---|---|---|---|
| S0 | corn-soy, no cover | reference | 0 | low | 0 |
| S1 | cereal rye before soybean | 28% (SD 26); older 31% (29) | leak × r × (share of the field's 2016-25 years that are soybean after corn; median 0.44) | low: 27/28 Midwest location-years with no soy loss; PFI 20 of 29 trials no effect | 12-27.5 per ac per year (= $24-55 seed + drilling per planting, every other fall; termination not included) |
| S2 | 4-yr corn-soy-oats/alfalfa-alfalfa | 27% (SD 25); older 42% (12); 3-yr 15% (34) as context | leak × r | moderate (Marsden: yields similar or higher; 2 of 4 years are oats and hay) | not quantified (Marsden profit similar or greater; no verified $/ac) |
| S3 | prairie on ~10% of the field | CRP 85% (SD 9) on the converted 10% | leak × 0.10 × r (strip assumed to leak like the field average) | low per cropped acre | 24-39 per treated acre per year (ISU STRIPS; secondary, not yet in facts.json) |

**Why S3 is prairie on part of the field** (not bioreactors or saturated buffers):
- It is a rotation-type change the farmer controls on the field.
- It has Iowa evidence (STRIPS; INRS land retirement).
- The INRS 2024 tile-water practices (saturated buffers 45%, bioreactors 24% of treated drainage) are named in the S3 gaps as the options to ask about for tile water.
- We do not credit strips with intercepting tile water.

**N kept, lb N/ac/yr.** p50 is a typical single year; the mean is the long-run average.

| | median field p50 | spread of field p50 (p10-p90 across fields) | median field p10-p90 | median field mean | fertilizer value, median field mean |
|---|---|---|---|---|---|
| S1 | 0.7 | 0.3-1.5 | 0.0-4.9 | 1.7 | $1.06/ac |
| S2 | 1.7 | 0.8-3.0 | 0.0-10.9 | 3.8 | $2.34/ac |
| S3 | 0.9 | 0.6-1.3 | 0.1-2.5 | 1.1 | $0.69/ac |

Why these are small:
1. They are river-delivered amounts.
2. Drought years (2020-23) leak almost nothing.
3. The 2024 efficiencies are lower than the older table.
4. Rye before soybean acts only about every other year.

Fertilizer value is an upper bound (the next crop does not recover all retained N). It is also counted at the river, so in that sense it understates the N kept at the field edge. The cards say both.

## 6. Limitations
- **Grid cells, not fields.** A field is a 400 m grid cell. Its N rate, manure, tile layout and tillage are unknown.
- **Coarse weather.** POWER is about 50 km MERRA-2; IMERG daily is blocked (BLOCKERS.md). Storm days ≥ 25 mm are rare at that scale (about 2-7 per year).
- **Interannual signal is water.** The calibration makes basin totals match by construction. The independent evidence is the r ≈ 0.74 interannual tracking, which is mostly water-driven.
- **Uncertain multipliers.** The tile multiplier m and ε are literature-anchored but not estimated from our data. m barely changes rankings (Spearman ≥ 0.975).
- **2016-19 field values** reuse each field's 2020-25 relative cover pattern.
- **No lag modelled.** Annual calibration on calendar years ignores within-year carry-over (for example fall-applied N leaving the next spring) and the Saylorville lag.

## 7. Inputs that changed during this build / rerun needs
Final outputs were generated **after** the orchestrator's refresh landed. Mtimes are recorded in `basin_index_check.json` → `input_mtimes`:
- hls_field_ts / field_year / field_month: 22:43 (spike-scene fix);
- cover_huc12_8day and cover_hls_huc12_8day (the HLS fill for the 2025 MODIS gap, now used): 22:43;
- hls_vs_modis.json: 22:44 (the monthly MODIS→HLS bias is read from it).

The final run came after all of these; results moved by less than 0.1 lb/ac between the pre- and post-refresh runs. Rerun both scripts after any change to POWER, NWIS, cover, HLS or facts.json; no code change is needed.

## 8. Notes for the exporter and frontend
- Strategy `n_loss_reduction.mean/lo/hi` are fractions; lo/hi are p10/p90 of the clipped prior. For S3 they are the whole-field effect (0.085).
- **S2 `cost_usd_ac.lo/hi` are null (not quantified).** `farmer.js` currently treats a null midpoint as $0 in the "low net cost" ranking. It should treat it as unknown.
- `leak_index`: fields use 1 = focus-area average; HUC-12s use 1 = basin average per row-crop ha. `share_of_basin_leak` is 0-1.
- `field_detail.json` is 4.7 MB as one file; split by HUC-12 if the web budget needs it.
- Facts to add for verification: the ISU STRIPS cost ($24-39 per treated acre per year), and the McIsaac & Hu / David et al. 2010 tile-delivery ratio.
