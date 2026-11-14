# Module `fields`: focus area, field cells and per-field living cover from NASA HLS

Scripts (run in order; each is re-runnable and caches its raw inputs):
```
python3 pipeline/p10_focus_area.py   # ~5 s   -> data/processed/focus_area.json
python3 pipeline/p11_hls_fetch.py    # ~12 min first run with 6 threads; resumable; later runs only fetch new granules
                                     # (and re-read Oct-May granules whose cache predates the v2 aerosol/grid format)
python3 pipeline/p12_fields.py       # ~25 s  -> fields, hls_field_ts, field_month, field_year (.parquet)
python3 pipeline/p13_hls_vs_modis.py # ~5 s   -> hls_vs_modis.json (writes a 'skipped' note if MODIS output is missing)
```
`pipeline/fields_common.py` holds the shared helpers: signed and retrying COG reads, the CDL letter table and a PC
`usda-cdl` mosaic fallback. The code was adapted, by copying, from `shared/central_iowa_pipeline/pipeline/hls_*.py` and `cdl_fields.py`.

## Focus area (`focus_area.json`)
- **10 HUC-12s, 846 km², all inside HLS MGRS tile 15TUG.** The tile is the UTM 15N square 300000-409800 E, 4590240-4700040 N. Every HUC-12 is at least 500 m inside it.
- The block is the North Raccoon mainstem HUC-10 0710000608, Sac City to the Calhoun/Carroll line:
  - Drainage Ditch 73-, Drainage Ditch 25-, Cottonwood Cemetery- and Marrowbone Creek-North Raccoon River
  - Prairie Creek
  - Elk Run
- It also includes the outlet HUC-12s of three tributaries:
  - Camp Creek
  - Drainage Ditch 10-Lake Creek and Lake Creek
  - Purgatory Creek
- bbox: lon -95.043 to -94.564, lat 42.083 to 42.412. The block is contiguous, which the script checks.
- **Why this block:**
  - It is the tile-drained Des Moines Lobe headwater landscape of the high-nitrate North Raccoon. Des Moines Water Works sued the Sac, Calhoun and Buena Vista drainage districts here in 2015.
  - It is the most upstream North Raccoon block that fits in one HLS tile. The tile's north edge is about 42.44° N, so the Buena Vista headwaters fall in 15TUH.
  - Its CDL 2021 row-crop share is 79.9%. The other in-tile Raccoon HUC-12s average 72.4%.
  - The Hardin/Buttrick Creek block to the east has slightly more row crop (about 87%) but is further downstream. The full candidate table is in the json.
- `huc12.parquet` is unchanged. Its `in_focus` column belongs to the hydro module, which can set it from `focus_area.json`.

## Field cells (`fields.parquet`, 1,769 rows, key `field_id`)
**Grid:** 400 m × 400 m cells on EPSG:5070, with origin at multiples of 400 m. A cell belongs to the grid when its centre is inside a focus HUC-12. That gives 5,289 cells; they are listed in `data/raw/hls/cells.npz`.

**Field rule:** a cell is a field when at least 80% of its 30 m CDL pixels (pixels whose centre is in the cell, about 182 per cell) are one row-crop letter (C, S or R) in at least 7 of the 10 years 2016-2025.
- CDL source: `data/raw/cdl/cdl_<year>_basins.tif`, from the `cdl` agent. All `DONE_<year>` sentinels were present, so the PC fallback was not used.
- 1,769 of 5,289 cells (33%) pass. The 400 m cells often straddle two real fields with different crops in the same year, or include farmsteads and ditches. The 80% rule is therefore strict, as intended.

| column | type | meaning |
|---|---|---|
| field_id | str | 'F' + 5-digit cell index (stable for this focus area; index into cells.npz) |
| lon, lat | float | cell centre, WGS84 (5 decimals) |
| x5070, y5070 | float | cell centre, EPSG:5070 m |
| huc12 | str | focus HUC-12 containing the centre |
| area_ha | float32 | 16.0 |
| cdl_2016..cdl_2025 | str | majority CDL letter in the cell. Letters: C corn, S soy, R other row crop, W wheat, O small grain, H hay/alfalfa, P grass/pasture, X other (same scheme as shared notes/cdl.md) |
| crop_seq | str | 10 letters 2016..2025 |
| n_rowcrop_years | int8 | years meeting the ≥ 80% single-row-crop test (7-10) *(extra)* |
| drainagecl | str | most frequent dominant-component SSURGO drainage class over the 90 m gNATSGO mukey pixels in the cell |
| poorly_share | float32 | component-weighted share of the cell that is poorly or very poorly drained (mean `poorly_frac_comp`) *(extra)* |
| poorly_drained | bool | poorly_share ≥ 0.5 |
| slope_pct | float32 | mean NASADEM slope (%) of 30 m pixels in the cell, from `data/raw/terrain/slope_30m.tif` |
| power_cell_id | str | nearest POWER grid-cell centre (`power_cells.parquet`) |
| polygon | list | 5-point lon/lat ring of the 400 m square |

**Counts:**
- Fields per HUC-12: 060702 305, 060802 231, 060806 217, 060803 210, 060804 194, 060505 172, 060604 161, 060805 103, 060801 95, 060605 81.
- Sequences: 521 SCSCSCSCSC and 485 CSCSCSCSCS (57% strict alternation), 31 CCCCCCCCCC.
- Drainage: 899 poorly, 25 very poorly, 206 somewhat poorly, 281 moderately well, 357 well drained. 39.5% of fields are `poorly_drained`.
- Slope: median 2.65% (range 1.1-5.9).
- POWER cells: p42.50_-95.000 755, p42.00_-95.000 426, p42.50_-94.375 372, p42.00_-94.375 216.

## HLS processing (`p11_hls_fetch.py`)
**Source:** NASA HLS v2.0 on Planetary Computer, `hls2-l30` (Landsat 8/9) and `hls2-s30` (Sentinel-2 A/B/C), tile T15TUG.
- Granules whose footprint intersects the focus bbox, 2020-01-05 to 2026-10-29, with eo:cloud_cover ≤ 80. That is 591 granules: 296 L30 and 295 S30.
- 491 granules had clear focus pixels and were used: 256 L30 and 235 S30. (Before the S30 high-aerosol mask: 522, with 266 S30.)

**Reads:** windowed reads of the focus window only (1330 × 1248 px), at native 30 m.
- Bands: Fmask, B03 green, B04 red, NIR (B05 for L30, B8A for S30), SWIR1 (B06 / B11) and SWIR2 (B07 / B12).
- Speed: about 8 s per granule, 12 min total with 6 threads.
- The URL is re-signed on every retry, so an expired SAS token (403) is refreshed.
- Cache: `data/raw/hls/g/<item>.npz`, written atomically.

**Clear pixel:**
- Fmask is not 255.
- Fmask bits 1-4 (cloud, adjacent, shadow, snow/ice) are all 0.
- **S30 only, Oct 1 to May 31:** Fmask aerosol level (bits 6-7) is not 11 (high).
- All bands are > 0 and not -9999.
- Scale factor 0.0001.

**Why high aerosol is masked on S30 but not on L30.** Green spike scenes outside the old Nov 15-Apr 30 QA window were getting through as clear. In S30 2024-05-03, 67.5% of fields read as living, against 3.2% on Apr 23 and 1.7% on May 17. In that scene 99.8% of the clear pixels carry the high-aerosol flag.
- S30: high-aerosol pixels read green. The 33 Oct-May S30 scenes with more than 90% high-aerosol pixels had a median field living share of 0.32 (median NDVI 0.28), against 0.02 for the other scenes. Within partly flagged scenes, masking lowers the scene-median NDVI by 0.01-0.02.
- L30: the flag is common in winter. It covers 40-70% of the clear pixels in most Dec-Feb scenes, near snow and over bright soil. Those pixels are **not** green: the 12 L30 scenes with more than 90% flagged had median NDVI 0.216 and living share 0.01.
  - Masking L30 as well was tried first. It deleted every L30 scene from Dec 2022 to Feb 2023 (Dec 30, Jan 15 and Feb 15). That opened a gap of more than 120 days, cut crop-year 2023 `days_known` to 230, and removed 16% of clear field observations. So L30 is not masked.
- Jun-Sep is never masked, because canopies sit far above 0.30.
- Effect: 14 of the 28 S30/L30 scenes that the old window check dropped now have no clear fields left. 30.7 M S30 pixels are masked in total.

**Cache v2** (all Oct-May granules) adds `grid`, the per-cell count of clear pixels with NDVI ≥ 0.200, 0.205, ... 0.450. p12 uses it to apply the S30 offset before thresholding. A rerun of p11 re-reads any Oct-May granule whose cache is v1 or was made under a different aerosol rule. The re-read of 341 + 181 granules took about 10 min.

**Cell means:** each value is a mean over the cell's **inner** pixels, meaning centres at least 30 m inside the cell. That is 121-140 pixels per cell, median 128. Stored per cell:
- n_clear
- mean NDVI, NDTI = (SWIR1-SWIR2)/(SWIR1+SWIR2) and GCVI = NIR/green - 1 (clipped to [-1, 20])
- pixel shares with NDVI ≥ 0.25, 0.30 and 0.35

## `hls_field_ts.parquet` (474,910 rows, 440,680 clear; key field_id, date)
| column | type | meaning |
|---|---|---|
| field_id | category | |
| date | date | acquisition date (UTC ~17:00 = local morning) |
| sensor | category | L30 / S30 |
| ndvi, ndti, gcvi | float32 | cell means of pixel indices (3 decimals) |
| live_px_share | float32 | share of clear inner pixels with NDVI ≥ 0.30, after the S30 offset (below) for S30 Oct-May rows *(extra)* |
| clear_share | float32 | clear inner pixels / inner pixels *(extra)* |
| clear | bool | clear_share ≥ 0.6 **and** the scene passed the spike QA below. Rows with clear_share 0.2-0.6 are kept as clear=False |
| ndvi_harm | float32 | `ndvi` minus the S30 offset on S30 Oct-May rows, otherwise the same as `ndvi`. Used for the spike test and the fall-minimum timing *(extra)* |

**Same-day duplicates** (L30 + S30, or two S30 granules on one day): the row that is clear wins, then the one with more clear pixels, then L30.

**S30 → L30 dormant-season offset.** S30 reads slightly greener than L30 over residue and soil.
- Estimate: same-day L30/S30 pairs of clear field cells, Nov-Apr, on days with at least 50 pairs. Take the median S30 - L30 cell-mean NDVI for each day, then the median over days.
- Result: **+0.0076 NDVI** from 13 pair-days and 8,808 pairs (IQR of the daily medians +0.000 to +0.010). Jun-Sep: +0.005.
- A check made before the S30 high-aerosol mask measured +0.016. Most of that gap was the green high-aerosol S30 pixels.
- Applied to S30 observations from Oct 1 to May 31: each pixel's NDVI is lowered by 0.0076 before thresholding. In practice the share at threshold t is read at t + 0.0076 from the cache-v2 count grid, interpolating linearly. All three thresholds (0.25, 0.30, 0.35) are adjusted.
- Jun-Sep S30 is not adjusted. Raw `ndvi` is kept unchanged; the adjusted value is `ndvi_harm`.
- The estimate is recomputed on every run and saved in `p12_report.json` (`s30_l30_offset`, with per-day values).

**Scene spike QA** replaces the old Nov 15-Apr 30 rule (median field NDVI > 0.255). It applies to scenes from Oct 1 to May 31 with at least 20 clear field cells.
- A scene is set to clear=False when either holds against **both** its nearest earlier and its nearest later scene within 20 days:
  - its median field `ndvi_harm` is more than 0.04 higher, or
  - its living share (cell-median NDVI ≥ 0.30) is more than 0.25 higher.
- Neighbours are unflagged scenes with at least 20 clear field cells on other dates. When a date has several scenes, the one with the most fields is used. The test repeats until no scene changes.
- 4 of 244 scenes were flagged:
  - L30 2022-10-02: living 0.63 against 0.39 and 0.44
  - S30 2023-12-30: 0.56 against 0.06 and 0.02
  - L30 2024-05-24: 0.62 against 0.03 and 0.08
  - L30 2025-03-09: 0.35 against 0.00 and 0.00; median 0.290 against 0.214 and 0.212
- S30 2024-05-03 no longer has any clear fields, because the aerosol mask removed them.
- **S30 2021-05-09 is not removed.** The aerosol mask lowers it from 36% to 22% living (644 fields left). Its next scene, L30 2021-05-24, is a cloudy 78% scene with only 85 clear fields, and it reads 26% living. So the scene is not above both neighbours.
  - On a pixel re-read, even the low-aerosol pixels of May 9 have median NDVI 0.28, against 0.25 on May 4. So the cause is not aerosol alone, and it may be a wet-surface or haze effect.
  - The late-May 2021 values come from this scene and a few cloudy scenes. **Treat May 2021 as uncertain.**
- Of the old rule's 28 dropped scenes: 14 have no clear fields left after the aerosol mask, 2 are flagged by the spike test, and 12 are kept. Those 12 have a median `ndvi_harm` of 0.23-0.27 and a living share of 0.00-0.08, apart from S30 2021-03-05 (31 fields, 0.23).

**Clear observations per field-year:** median 34 (p10 23, p90 47) over all years. For 2021-2026 the p10/median/p90 is 28/36/48; before the S30 aerosol mask it was 32/40/53. 2020 is lower (22): PC has few L30 granules in 2020-21, and crop year 2020 has no Oct-Dec 2019 data.

## Living cover definition
A clear field observation counts as **living** when at least 50% of the cell's clear pixels have NDVI ≥ 0.30, which is the same as cell-median NDVI ≥ 0.30. The NDVI ≥ 0.30 threshold follows the contract. The median is used instead of the mean so that grassed waterways and field-edge grass, which can make up to 20% of a cell, cannot make an April field look covered. Bare means not living.

**Daily status:** the pixel share is linearly interpolated between clear observations. Gaps up to 120 days are interpolated (this covers snowy winters); longer gaps are unknown. A day is living when the interpolated share is at least 0.5.

**Snow:** pixels flagged as snow are not clear, so snow days are interpolated from the bracketing snow-free observations.

## `field_month.parquet` (141,157 rows; key field_id, year, month; **calendar** year)
- `living_frac`, `bare_frac`: shares of the month's days (with known daily status) that are living or bare.
- `n_obs`: clear observations in the month.
- `interp_only` *(extra)*: bool, `n_obs == 0`. The month's status is interpolated entirely from neighbouring months, and the UI should grey it out. Share of field-months that are interpolation only:

  | Month | Jan | Feb | Mar | Apr | Nov | Dec | other months |
  |---|---|---|---|---|---|---|---|
  | interp_only | 28% | 55% | 16% | 1.5% | 3.9% | 44% | 0 |

  Before the S30 aerosol mask these were Jan 24%, Feb 57%, Mar 14% and Dec 27%. December lost S30 scenes that were high-aerosol and green.
- Mean `living_frac` across fields, by month (before the fixes in brackets):

  | Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | living_frac | .012 (.015) | .013 (.011) | .012 (.011) | .018 (.023) | .096 (.14) | .91 | 1.0 | 1.0 | .91 | .24 (.26) | .021 (.018) | .016 (.020) |

  These are the leak-calendar months: no living roots from October to May.
- May `living_frac` by year: 2020 .014 (.044), 2021 .31 (.39), 2022 .028 (.039), 2023 .11 (.12), **2024 .049 (.23)**, 2025 .10 (.11), 2026 .052 (.055).
  - 2024 was the S30 2024-05-03 aerosol spike plus the L30 2024-05-24 spike.
  - For 2021, see the caveat on S30 2021-05-09 above.

## `field_year.parquet` (12,383 rows = 1,769 fields × crop years 2020-2026; key field_id, year)
**Year convention:** `year` is the **crop year**, which is the USGS water year, Oct 1 of year-1 to Sep 30 of year. The winter of Nov 2024 to Apr 2025 belongs to crop year 2025, together with the 2025 cash crop.
- Crop year 2027 (data for Oct 2026 only) is not written. The rule: a crop year is written only when the data reach Sep 1 of that year. (The old check `cal_m[m].max() < 9` could never trigger; it is replaced by `days[m].max() < Sep 1 of Y`, with the same result here.)
- Crop year 2020 is missing Oct-Dec 2019, because PC HLS starts in January 2020. For that year `bare_days_octdec` = -1, `days_known` is about 185 and the fall score is NaN.

| column | type | meaning |
|---|---|---|
| crop | str | CDL letter of calendar `year` (null for 2026: CDL 2026 not released) |
| prev_crop | str | CDL letter of year-1 (the crop harvested before this winter) *(extra)* |
| winter_cover_score | float32 0-1 | max(s_spring, s_fall) |
| s_spring, s_fall | float32 | *(extra)* window scores, see below (NaN = no obs) |
| winter_cover | bool | see below |
| bare_days_total | int16 | bare days in the crop year (known days only) |
| bare_days_aprjun | int16 | bare days Apr 1-Jun 30 of `year` |
| bare_days_octdec | int16 | bare days Oct 1-Dec 31 of year-1 (-1 = no data) |
| days_known | int16 | days in the crop year with a known daily status *(extra)* |
| green_up_doy | int16 | first day of year (≥ DOY 60) of calendar `year` that starts ≥ 15 consecutive living days (-1 = none). On fields with a cover crop, hay or volunteer growth this is the green-up of that cover, not cash-crop emergence. Median DOY: H 91, O 131, C 151, S 157 |
| n_clear_obs | int16 | clear obs in the crop year |
| n_obs_spring, n_obs_fall | int16 | clear obs in the spring / fall windows *(extra)* |

**Winter cover detection** uses two windows:
- Fall: Oct 15 to Dec 15 of year-1, after the previous crop is harvested.
- Spring: Mar 15 to May 10 of year, before the new crop canopy (corn and soy fields have median NDVI of about 0.23-0.27 until mid-May).

How each window is scored:
- **s** is the second-highest `live_px_share` over the window's clear observations. If the window has only one observation, s is that value. Using the second-highest makes s robust to a single noisy scene.
- Fall observations count only after the field's NDVI minimum between Sep 15 and Nov 30, which marks senescence or harvest. Standing green crops and late soybeans therefore do not count.
- `winter_cover` is true when at least 2 clear observations in the spring window, or at least 2 post-harvest observations in the fall window, have a cell-median NDVI ≥ 0.30.
- Of the 269 field-years flagged as covered, 89% are detected in spring and 51% in fall; some are detected in both.

| crop year | 2020* | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| % fields with detected winter cover (NDVI 0.30) | 0.5 | 3.3 | 1.2 | 0.8 | 4.0 | 1.3 | 4.2 |
| (before the aerosol/offset/spike fixes) | 1.0 | 4.2 | 2.2 | 1.0 | 4.7 | 1.7 | 4.7 |
| sensitivity: threshold 0.25 | 5.9 | 21.8 | 7.3 | 7.3 | 18.0 | 11.1 | 20.3 |
| sensitivity: threshold 0.35 | 0.2 | 2.7 | 0.8 | 0.4 | 3.1 | 1.2 | 2.8 |
| median bare days (0.30) | 81* | 233 | 241 | 236 | 244 | 238 | 239 |
| median bare days Apr-Jun / Oct-Dec | 62 / - | 51 / 92 | 68 / 84 | 57 / 88 | 63 / 91 | 59 / 88 | 62 / 88 |
| median green-up DOY | 156 | 143 | 159 | 148 | 155 | 150 | 153 |

\* 2020 spring only, partial year.

What the table shows:
- **These are lower bounds on cover-crop use, not adoption estimates.** Detection runs at 0.8-4.2% of fields a year. 8.8% of fields show cover in at least one of 2021-2026 (10.5% before the fixes), and 3.8% in at least two. Iowa's statewide cover-crop adoption is about 17% of cropland. The method misses:
  - covers that never reach a cell-median NDVI of 0.30, such as thin or late-seeded rye, which is the most common Iowa cover;
  - covers terminated before Mar 15 with no fall growth;
  - covers hidden by snow or by winter observation gaps;
  - covers on only part of a 16 ha cell.
- **0.35 gives nearly the same answer as 0.30,** so the covers that are detected are strong green-ups. Example: about 75 fields in spring 2021 rose from 0.30 to 0.41 NDVI in late April, then dropped in early May at termination.
- **0.25 is not usable.** Residue and soil sit at NDVI 0.21-0.25, so that threshold flags 6-22% of fields. This is lower than before (12-39%) because of the aerosol mask and the offset.

By previous and current crop (2021-2025): corn → soy (the cereal-rye-before-soy niche) runs 0.5-3.1%, corn → corn 1.1-7.6% (2024), and soy → corn 0.8-3.7%.

**Seasonal curves look right.** Median NDVI of clear observations on corn (C) and soy (S) field-years, by month:

| Crop | Jan | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|---|
| Corn | .22 | .23 | .23 | .26 | .61 | .89 | .88 | .60 | .28 | .23 |
| Soy | .21 | .22 | .22 | .25 | .42 | .85 | .90 | .50 | .25 | .23 |

Corn greens up earlier, in June, and soy peaks later, in August. Median green-up DOY is 151 for corn and 157 for soy.

## `hls_vs_modis.json`
Compares HLS field living share with MODIS 13Q1 living share on row-crop pixels (`cover_huc12_8day.parquet`), per focus HUC-12 and per 16-day composite window. A pair needs at least 30 HLS field observations and a MODIS valid_frac of at least 0.5.

| Comparison | n | r | bias (MODIS - HLS) | Notes |
|---|---|---|---|---|
| All pairs | 2,270 | 0.942 | +0.085 | RMSE 0.174; same living/bare class 93.8% of the time |
| **Deseasonalized** (minus all-HUC monthly means) | 2,270 | **0.631** | 0 | the pooled r is mostly the shared seasonal cycle |
| Whole focus area | 245 | 0.946 | +0.083 | |
| Mean NDVI | 2,270 | 0.986 | +0.020 | |
| Fall window (Oct 15-Dec 15) | 347 | 0.83 | +0.04 | |
| Spring window (Mar 15-May 10) | 439 | 0.52 | +0.13 | |
| **Mar-May** | 668 | **0.49** | **+0.17** | MODIS May living 0.39 vs HLS 0.045 |
| HUC-12 ranking, Apr-May HUC-12 means (10 HUC-12s) | 10 | **0.94** (Spearman 0.84) | | MODIS 0.22-0.37 vs HLS 0.02-0.07 |
| HUC-12 ranking, per composite (Apr-May, ≥ 5 HUC-12s) | 46 | Spearman median **0.55** | | |

Before the fixes the same statistics were: deseasonalized r 0.63; Mar-May r 0.40 with bias +0.15; HUC means r 0.92 (HLS 0.03-0.10); per-composite Spearman 0.58.

**Conclusion:** MODIS ranks HUC-12s well, but it overstates the spring living share in absolute terms (Apr-May HUC-12 means 0.22-0.37 against 0.02-0.07 for HLS). Use MODIS as a relative index across HUC-12s, and use HLS for the absolute field-level bare share. The same statement is in the json's `conclusion` field. MODIS reads greener because:
- MODIS composites keep the highest-NDVI day of the 16 (maximum-value compositing).
- A 250 m pixel mixes in edges, waterways and early weeds.

## Caveats
- **PC's HLS holdings are incomplete.** For 2023, NASA CMR lists 85 HLSS30 and 79 HLSL30 T15TUG granules with cloud cover ≤ 80. PC returns 42 S30 and 53 L30 that intersect the focus bbox. 2020-21 L30 holdings are also thin (22-25 per year).
  - Getting the rest from LP DAAC needs Earthdata login, which is not required here.
  - Observation density is still 32-53 clear observations per field-year from 2021 on.
- A field cell is a 16 ha grid square, not a surveyed field polygon. Neighbouring cells are not independent.
- **Winter-cover rates are lower bounds on cover-crop use, not adoption estimates.** Detection is 0.8-4.2% of fields a year and 8.8% in any year, against roughly 17% statewide adoption. Detection cannot see:
  - a cover seeded late and terminated before Mar 15 without fall growth;
  - a cover that never reaches a cell-median NDVI of 0.30 (thin rye);
  - a cover under snow;
  - a cover on part of a cell only.
  
  The same misses make bare-day counts upper bounds on "no living roots".
- Fmask misses some thin cloud and haze. On L30 those observations usually read low NDVI. On S30, high aerosol reads green, which is why it is masked Oct-May. Moderate-aerosol S30 pixels are kept. The spike test catches whole-scene residue, but not a spike that has a high neighbour (S30 2021-05-09).
- Months with `interp_only` = true (no clear observation, most often Dec-Feb) carry interpolated status only.
- Soils come from 90 m gNATSGO mukeys with dominant-component attributes, and slope from smoothed NASADEM 30 m, via the cdl agent's p07.

## Deviations from contract
- Extra columns are marked *(extra)* above.
- Living is decided on the cell-median NDVI ≥ 0.30 (the pixel share at least 0.5), not the cell-mean NDVI. The mean NDVI is still stored in `ndvi`.
- `field_month.bare_frac` and `living_frac` are day-weighted shares from the interpolated daily status, not shares of observations. `n_obs` is the observation count.
- `field_year.year` is the crop year (water year). `field_month` uses calendar year.
- `-1` is the sentinel for an unknown int16 value.
- Dormant-season scene QA is a neighbour spike test (Oct 1-May 31), not a date-window NDVI cap. On top of that, S30 high-aerosol pixels are masked Oct-May, and S30 is harmonised to L30 with a -0.0076 NDVI offset Oct-May before the 0.30 threshold.

## Provenance
- HLS v2.0 L30/S30: https://planetarycomputer.microsoft.com/api/stac/v1 (collections `hls2-l30`, `hls2-s30`); NASA LP DAAC HLS, doi:10.5067/HLS/HLSL30.002 and 10.5067/HLS/HLSS30.002
- USDA NASS CDL 2016-2025: `data/raw/cdl/cdl_<year>_basins.tif` (cdl agent: PC `usda-cdl` 2016-2021 and NASS national zips 2022-2025). Focus selection used PC `usda-cdl` 2021 directly.
- SSURGO/gNATSGO via the cdl agent (`soils_mukey.parquet`, `mukey_90m.tif`); NASADEM slope (`slope_30m.tif`).
- WBD HUC-12: `huc12.parquet` (hydro, p01).
