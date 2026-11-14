# Module `fields_model`: field leak score, HUC-12 hotspot index, river calibration, farmer strategies

Scripts (re-runnable end to end, no network, about 30 s each):
```
python3 model/m05_fields.py       # drainage fit, loads, living-cover calibration, HUC-12 index, river calibration, validation, field scores
python3 model/m06_strategies.py   # strategy cards + per-field Monte Carlo of N kept
```
Every number comes from `data/processed/*`, `docs/facts.json` (read by id at run time) and
`shared/evidence/evidence_priors.json`. The code only adds model settings: thresholds, grids and seeds.

> **What the model does and does not show.** The model places leak in time and space where bare ground meets wet soil, and fields sum to the measured river load. How much each practice cuts nitrate comes from Iowa trials (INRS 2024), not from our satellite data. Year-to-year load is explained mostly by water. The river does **not** validate practice effects.

**Headline statistic = the long-run mean (lb N/acre/yr).** p10-p90 is the single-year spread ("in 8 of 10 years"); p50 is one typical year. A one-year median is misleading for a practice that acts only in some years: rye before soybean acts in about half the years. `leak_pctile` and `leak_index` use the mean.

## Outputs (model/out/)

| file | content |
|---|---|
| `field_scores.parquet` | 1,769 fields, one row each. Leak values: `leak_lbN_ac_yr_mean` (headline), `leak_lbN_ac_yr_p10/p50/p90`, `lbN_ac_<2016..2025>` (central). Ranking: `leak_index` (mean ÷ focus-area mean), `leak_pctile` (0-100, on the mean). Calendar: `cal_*` (12-month lists incl. `cal_interp_only`). Rotation: `frac_leak_oct_may`, `frac_leak_apr_jun`, `freq_soy_after_corn_2016_2025`. Also `hls_fallback_share` and `leak_q200` (quantile function for m06) |
| `huc12_scores.parquet` | 290 HUC-12s. kgN_ha_<year> per row-crop ha, kgN_ha_mean, lbN_ac_mean, contrib_t_mean, share_of_basin_leak (2016-25 mean), share_of_basin_leak_recent (2023-25), share_of_basin_area, leak_index (1 = basin average per row-crop ha), rank, bare_days_wet, row_crop_share, poorly_drained_share |
| `huc12_props.json` | `{huc12: props}` in the web `huc12.geojson` contract shape, plus `lbN_ac_yr`, `share_of_basin_leak_recent`, `n_in_basin` |
| `fields.geojson` | contract props + `lbN_ac_yr_mean` (headline) and `lbN_ac_yr_p50` |
| `field_detail/<huc12>.json` | web contract, split into 10 files (0.23-0.86 MB each, 5.0 MB total). The single `field_detail.json` is written only if it is ≤ 3 MB, which it is not, so it is removed. Extras are listed below the table |
| `strategies.json` | web contract S0-S3 + `fert_value_note` per card, `method` (opens with the sentence in the box above), `units.headline`, `efficiency_draws`. `cost_usd_ac` has `basis` and `source` |
| `basin_index_check.json` | drainage fit, loads + gap-fill cross-validation, living-cover calibration, calibration table, validation check, sensitivities, input mtimes |

Extras in `field_detail`:
- `leak.lbN_ac_yr.mean`, `leak.wet_year_2016`, `leak.by_year`;
- `strategies.<S>.lbN_kept_ac.mean` and `fert_value_usd_ac.mean`;
- `strategies.<S>.wet_year_2016.lbN_kept_ac{mean, p10, p90}`;
- `strategies.S1.note` (fields with no soybean-after-corn years);
- `calendar.leak_share`, `calendar.leak_lb_ac` (= leak_share × mean, lb/ac per month), `calendar.interp_only` (bool per month; grey it out) and `calendar.interp_only_share`;
- `why_field`;
- `ndvi_recent` thinned evenly to ≤ 40 points, 2 decimals.

## 1. Daily drainage driver (per NASA POWER cell)
`D = (liquid rain + snowmelt) × clip((GWETROOT_yesterday − w0)/dw, 0, 1)`, in mm/day.
- **Liquid rain:** PRECTOTCORR − PRECSNOLAND.
- **Snowmelt:** a snow-water store fills with snowfall and releases water in proportion to the day's relative loss of snow depth (SNODP), so no snow density is assumed.
- **Missing snowfall:** PRECSNOLAND is missing from 2026-10-01; precipitation then counts as snow when T2M ≤ 0 °C.

Why the wetness gate: tiles drain only near or above field capacity, so rain on dry soil refills storage instead (the 2020-23 drought).

**Fitted to measured monthly runoff** (USGS flow ÷ basin area, 2016-2025, 896-point grid): **w0 = 0.45, dw = 0.10**. The routing constant k = 10 d is used only in the fit.

| Pearson r vs measured runoff | monthly, Raccoon | monthly, Des Moines | annual, Raccoon | annual, Des Moines |
|---|---|---|---|---|
| wet-soil gate | 0.91 | 0.91 | 0.95 | 0.96 |
| no gate (all rain + melt) | 0.64 | 0.70 | 0.85 | 0.92 |

## 2. Measured annual loads (calibration target)
**Gap filling.** Load = no3_mgL × q_cfs × 2.4466. Gaps are filled with a regression of ln C on ln Q, ln Q², two seasonal harmonics and a calendar-year level, plus residuals interpolated linearly in time.

**Gap-fill uncertainty from cross-validation.** Hidden blocks of 3-90 days had a load-normalised RMSE of 7-34%. Errors are combined per year by gap length.
- Annual SD is ≤ 2.5%, except Des Moines 2016 at 7.9% (Jan-Mar 2016 missing; 32% of that year's load is filled).
- Sensor and rating-curve error are not included.

**Share of the river load from row-crop land, s ~ U[0.759, 0.892].** Both bounds come from INRS (primary) and CDL:

s = (1 − point share) × row-crop share of the land-based load

- Point sources are 8% (= 1 − INRS nonpoint 92%).
- Non-row-crop land (grass, hay, small grain, forest, other) leaks per ha either as much as row crop (lower bound) or 15% of it (= 1 − INRS CRP 85%; upper bound).
- CISWRA's "70-80% from agriculture" (secondary) is no longer used.

**Calibration table.** kg N per row-crop ha per year from row-crop land, central s = 0.825 (lb/ac in brackets). The lo-hi range is ×0.92 to ×1.08.

| year | Raccoon (05484500) | Des Moines (05482000) |
|---|---|---|
| 2016 | 38.5 (34.4) | 44.7 (39.9) |
| 2017 | 22.7 (20.2) | 23.7 (21.2) |
| 2018 | 31.7 (28.3) | 36.3 (32.4) |
| 2019 | 28.3 (25.3) | 25.8 (23.0) |
| 2020 | 11.0 (9.9) | 14.3 (12.7) |
| 2021 | 1.4 (1.2) | 1.5 (1.4) |
| 2022 | 9.3 (8.3) | 8.0 (7.2) |
| 2023 | 3.3 (3.0) | 4.9 (4.4) |
| 2024 | 15.8 (14.1) | 28.7 (25.6) |
| 2025 | 23.1 (20.6) | 24.3 (21.7) |
| mean | 18.5 (16.5) | 21.2 (18.9) |

These are loads **delivered to the gauges**. Nitrate removed in ditches, streams and Saylorville is not counted, so edge-of-field losses are larger. That fits ISU's "about 30 lb N/ac, 15-50" once the drought years are included.

## 3. Leak index
`daily leak = [bare + ε·(1 − bare)] × D × [1 + (m − 1)·poorly_drained_share]`, calibrated per basin and year.

| factor | value | source / estimation |
|---|---|---|
| bare, HUC-12 | MODIS 13Q1 bare share on row-crop pixels | MODIS is used as a relative index on the HLS scale: the monthly MODIS−HLS bias (`hls_vs_modis.json`, by day of year; May 0.34) is subtracted. Gaps > 60 d use HUC-12 day-of-year climatology. The Jul-Nov 2025 gap uses `cover_hls_huc12_8day.parquet` (HLS quantile-mapped to MODIS, 4,913 rows) |
| bare, field | 1 − interpolated HLS `live_px_share` | Linear between clear observations, gaps ≤ 120 d. Otherwise the HUC-12 corrected MODIS is used (4.1% of field-days, mostly winter snow). A generic spring spike-scene filter drops 0 scenes on the fixed data |
| **ε, living-cover factor** | **0.232, calibrated** | Fields with **HLS-observed winter cover** (`field_year.winter_cover`, crop years 2021-25, n = 187 field-years) are compared with uncovered fields in the same HUC-12 and crop year, with drainage differences divided out. ε is set so the mean modelled crop-year cut equals the **INRS 2024 rye efficiency, 28%**, the prior the S1 card uses. With the previous ε = 0.15 (CRP-based) the cut was 32%; with ε = 0 it is 41%. Index and cards are now consistent |
| m, tile delivery | U[1, 4] grid, central 2.5 | 1 = no difference. 4 = upper end implied by McIsaac & Hu (2004) via David et al. (2010): river export = 100% of net N inputs in tiled central Illinois vs 25-37% in the non-tiled south. That fact is now `tile_delivery_mcisaac_hu` (secondary); the 2.7-4× ratio is our arithmetic. HUC-12 share ranking vs m: Spearman ≥ 0.975 |
| crop year | 1 for corn and soybean | facts.json `isu_lbN_acre_yr` note: "Corn and soybean losses are similar" |
| weather at a field | bilinear between the 4 surrounding POWER cell centres | Nearest-cell lookup created a false step at the 42.25° N cell edge |

**Calibration.** HUC-12 kg/ha = k × index, so that Σ(kg/ha × row-crop ha) = s × measured load, per basin and year. Fields are scaled within their HUC-12:

field kg/ha(y) = HUC-12 kg/ha(y) × field index(y) / mean field index in that HUC-12(y)

The HLS index is 1.06-1.36× the MODIS index. For 2016-19 each field's mean 2020-25 relative index is used.

**Field uncertainty.** A Monte Carlo of 4,000 draws over the weather year (uniform 2016-2025), s, the load gap-fill error and m.

| lb N/ac/yr | value |
|---|---|
| median field, long-run mean (headline) | **13.7** |
| median field, single-year p10 / p50 / p90 | 0.8 / 10.8 / 30.6 |
| field means, p5-p95 across fields | 8.8-20.0 |
| field means, median across fields | 13.7 |
| 2016 wet year, median field | 33.1 |

Poorly drained fields leak 1.35× more than well-drained ones.

**Calendar (2020-25 means).**
- `bare_frac` comes from HLS; `rain_mm`, `storm_days` (≥ 25 mm) and `wetness` (GWETROOT) from bilinear POWER.
- `leak_risk` = month ÷ the field's maximum month.
- `leak_lb_ac` = leak_share × the field's mean (magnitude).
- `interp_only[m]` = no clear HLS observation in that month in ≥ half of 2020-25. Fields flagged: Jan 64%, Feb 72%, Dec 55%, other months ≈ 0.
- On the average field, 91% of the leak falls Oct-May and 54% Apr-Jun.

**HUC-12 outputs.**
- `share_of_basin_leak` and `rank` use the 2016-25 mean.
- `bare_days_wet` = Σ bare share on days with D ≥ 1 mm, Mar-Jun + Sep-Dec, mean of 2023-25.

## 4. Validation check (uncalibrated index vs measured load per row-crop ha, 2016-2025, n = 20)

| test | Pearson | Spearman |
|---|---|---|
| pooled, both basins | 0.75 (p = 1e-4) | 0.84 |
| Raccoon only (n = 10) | 0.76 | 0.88 |
| Des Moines only (n = 10) | 0.75 | 0.78 |
| drainage only, no cover term | 0.79 | 0.90 |
| POWER precipitation only | 0.83 | 0.83 |
| measured runoff (reference) | 0.87 | 0.93 |

**Reading.**
1. Year-to-year load is driven by water. The index tracks it (r ≈ 0.75) but not better than drainage or rain alone.
2. The cover term does not improve interannual tracking. The partial r of the cover part with load, controlling for drainage, is −0.39 (p = 0.09). Pooled r runs 0.71 (ε = 0) → 0.75 (ε = 0.232) → 0.79 (ε = 1). Interannual MODIS bare share is mostly green-up timing (weather). The cover term rests on the INRS trial calibration in §3 and drives seasonal and field differences, which 20 basin-years cannot test.
3. **Per-area ratio Raccoon / Des Moines.** Index 0.72 vs measured 0.88; the year-to-year correlation of the ratios is r = 0.36 (n.s.). The index misses the between-basin level; the per-basin calibration absorbs it.
4. **Within-basin HUC-12 pattern unvalidated** (no sub-basin gauges).
   - The Raccoon ranking follows bare-and-wet days (r = 0.80), which come mostly from 50 km POWER weather, more than poorly drained share (r = 0.06).
   - The southern Raccoon HUC-12s rank top (Lower Mosquito Creek, Happy Run-Hardin Creek, West Branch Panther Creek).
   - The focus area ranks 17-105 of 105 (leak_index 0.64-1.06).
   - Present this as "where bare ground meets wet soil".

## 5. Strategies (m06)
**Priors.** INRS **Mar 2024 update** (`inrs_2024_update` in facts.json) is primary; the older table is shown as context.

**Draws.** Each efficiency is a normal **truncated to [0, 1] with its location solved so the mean equals the stated efficiency**; scale = stated SD. Draw means: 0.278, 0.270, 0.085. Each practice is applied to the field's own leak distribution, `leak_q200`, by Monte Carlo (4,000 draws).

**Headline mean** = field mean leak × efficiency × coverage, which is exact because the draws are independent.

**N price** U[$0.53 (ISU A1-88), $0.70 (AMS high)]. `fert_value_note` on each card says the value is an upper bound. For S1 it also says that N kept ahead of soybean has little fertilizer value for that crop.

| id | practice | prior | coverage | yield risk | cost $/ac (basis) |
|---|---|---|---|---|---|
| S0 | corn-soy, no cover | reference | 0 | low | 0 |
| S1 | cereal rye before soybean | 28% (SD 26); older 31% (29) | × share of the field's 2016-25 years that are soybean after corn (median 0.44) | low (27/28 Midwest location-years no soy loss; PFI 20/29) | 12-27.5 per ac per year (= $24-55 seed + drilling per planting, every other fall) |
| S2 | 4-yr corn-soy-oats/alfalfa-alfalfa | 27% (SD 25); older 42% (12); 3-yr 15% (34) as context | whole rotation | moderate | null, not quantified (Marsden profit similar or greater) |
| S3 | prairie on ~10% of the field | CRP 85% (SD 9) on the 10% | strip assumed to leak like the field average | low per cropped acre | 26-33 per treated acre per year (`strips_cost_usd_treated_ac`, secondary) |

**N kept, lb N/ac/yr, median field.**

| | long-run mean (headline) | single year p10-p90 | typical year (p50) | 2016 wet year | fertilizer value (mean) |
|---|---|---|---|---|---|
| S1 | 1.7 | 0.0-4.5 | 0.9 | 9.2 (a year with rye in place) | $1.02 |
| S2 | 3.7 | 0.2-9.9 | 2.0 | 8.9 | $2.28 |
| S3 | 1.2 | 0.1-2.5 | 0.9 | 2.8 | $0.72 |

Why the numbers are small:
1. They are counted as nitrate that would have reached the river.
2. The drought years leaked almost nothing.
3. The 2024 efficiencies are lower than the older table.
4. Rye before soybean acts about every other year.

**Who pays.**
- The EQIP 340 rate is labelled as coming from a third-party guide, not the NRCS booklet.
- The CP-43 "about 75% lower cost, $7-8 per treated acre" claim now cites the new fact `strips_crp_cost_reduction_pct` (secondary).
- The EQIP 328 rate stays hidden while it is unverified.

## 6. facts.json additions (made in this fix pass, appended; nothing else changed)
`strips_cost_usd_treated_ac`, `strips_crp_cost_reduction_pct` and `tile_delivery_mcisaac_hu` are all `secondary`. They come from web-search extraction because strips.nrem.iastate.edu and the David et al. PDF host do not resolve from this session. Allowing those hosts would let a verifier upgrade them.

## 7. Limitations
- **Grid cells, not fields.** A field is a 400 m grid cell. Its N rate, manure, tile layout and tillage are unknown.
- **Coarse weather.** POWER is about 50 km; IMERG daily is blocked.
- **Validation is mostly water.** Calibration matches basin totals by construction. The independent evidence is r ≈ 0.75 interannual tracking, which is mostly water-driven.
- **ε calibration.** ε is calibrated from 187 field-years and assumes HLS-detected cover behaves like INRS rye.
- **Tile multiplier.** m is literature-anchored; rankings are insensitive to it.
- **2016-19 field values** reuse each field's 2020-25 cover pattern. No carry-over or reservoir lag is modelled.

## 8. Inputs and reruns
The final run postdates all refreshed inputs; mtimes are in `basin_index_check.json` → `input_mtimes`:
- hls_field_ts / field_year / field_month: 22:43;
- cover_huc12_8day and cover_hls_huc12_8day: 22:43;
- hls_vs_modis.json: 22:44.

After any change to POWER, NWIS, cover, HLS or facts.json, rerun m05 then m06; no code change is needed.

## 9. Notes for the exporter and frontend
- Use `mean` as the headline number for leak, N kept and fertilizer value. Label p10-p90 as "in 8 of 10 years".
- `n_loss_reduction` values are fractions; lo/hi are p10/p90 of the truncated prior.
- S2 cost is null (unknown). It should not be ranked as $0.
- Grey out calendar months where `interp_only` is true.
- `field_detail` comes as split files only (`field_detail/<huc12>.json`).
- `leak_index`: fields 1 = focus-area mean; HUC-12s 1 = basin mean per row-crop ha.
