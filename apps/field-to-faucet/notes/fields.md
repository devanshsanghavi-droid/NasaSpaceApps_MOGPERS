# Module `fields`: focus area, field cells and per-field living cover from NASA HLS

Scripts (run in order; each is re-runnable and caches its raw inputs):
```
python3 pipeline/p10_focus_area.py   # ~5 s   -> data/processed/focus_area.json
python3 pipeline/p11_hls_fetch.py    # ~12 min first run with 6 threads; resumable; later runs only fetch new granules
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
- 522 granules had clear focus pixels and were used: 256 L30 and 266 S30.

**Reads:** windowed reads of the focus window only (1330 × 1248 px), at native 30 m.
- Bands: Fmask, B03 green, B04 red, NIR (B05 for L30, B8A for S30), SWIR1 (B06 / B11) and SWIR2 (B07 / B12).
- Speed: about 8 s per granule, 12 min total with 6 threads.
- The URL is re-signed on every retry, so an expired SAS token (403) is refreshed.
- Cache: `data/raw/hls/g/<item>.npz`, written atomically. Total cache 33 MB.

**Clear pixel:**
- Fmask is not 255.
- Fmask bits 1-4 (cloud, adjacent, shadow, snow/ice) are all 0.
- All bands are > 0 and not -9999.
- Scale factor 0.0001.

**Cell means:** each value is a mean over the cell's **inner** pixels, meaning centres at least 30 m inside the cell. That is 121-140 pixels per cell, median 128. Stored per cell:
- n_clear
- mean NDVI, NDTI = (SWIR1-SWIR2)/(SWIR1+SWIR2) and GCVI = NIR/green - 1 (clipped to [-1, 20])
- pixel shares with NDVI ≥ 0.25, 0.30 and 0.35

## `hls_field_ts.parquet` (536,500 rows, 490,645 clear; key field_id, date)
| column | type | meaning |
|---|---|---|
| field_id | category | |
| date | date | acquisition date (UTC ~17:00 = local morning) |
| sensor | category | L30 / S30 |
| ndvi, ndti, gcvi | float32 | cell means of pixel indices (3 decimals) |
| live_px_share | float32 | share of clear inner pixels with NDVI ≥ 0.30 *(extra)* |
| clear_share | float32 | clear inner pixels / inner pixels *(extra)* |
| clear | bool | clear_share ≥ 0.6 **and** the scene passed the dormant-season QA below. Rows with clear_share 0.2-0.6 are kept as clear=False |

**Same-day duplicates** (L30 + S30, or two S30 granules on one day): the row that is clear wins, then the one with more clear pixels, then L30.

**Dormant-season scene QA:** this applies to scenes from Nov 15 to Apr 30 with at least 20 clear fields.
- Normally the scene-median field NDVI sits at residue or soil level (0.21-0.25), and cover crops are under 10% of fields.
- 28 of 166 dormant scenes had a scene-wide median above 0.255 and were set to clear=False. 25 were S30, for example S30 2021-03-05 at 0.326 against 0.256 for L30 the same day.
- These scenes would otherwise have made bare fields look green in Feb and Mar. The full list is in `data/raw/hls/p12_report.json`.

**Clear observations per field-year:** median 39 (p10 24, p90 52) over all years. For 2021-2026 the p10/median/p90 is 32/40/53. 2020 is lower (22): PC has few L30 granules in 2020-21, and crop year 2020 has no Oct-Dec 2019 data.

## Living cover definition
A clear field observation counts as **living** when at least 50% of the cell's clear pixels have NDVI ≥ 0.30, which is the same as cell-median NDVI ≥ 0.30. The NDVI ≥ 0.30 threshold follows the contract. The median is used instead of the mean so that grassed waterways and field-edge grass, which can make up to 20% of a cell, cannot make an April field look covered. Bare means not living.

**Daily status:** the pixel share is linearly interpolated between clear observations. Gaps up to 120 days are interpolated (this covers snowy winters); longer gaps are unknown. A day is living when the interpolated share is at least 0.5.

**Snow:** pixels flagged as snow are not clear, so snow days are interpolated from the bracketing snow-free observations.

## `field_month.parquet` (142,016 rows; key field_id, year, month; **calendar** year)
- `living_frac`, `bare_frac`: shares of the month's days (with known daily status) that are living or bare.
- `n_obs`: clear observations in the month.
- Mean `living_frac` across fields, by month:

  | Month | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | living_frac | .015 | .011 | .011 | .023 | .14 | .91 | 1.0 | 1.0 | .91 | .26 | .018 | .020 |

  These are the leak-calendar months: no living roots from October to May.

## `field_year.parquet` (12,383 rows = 1,769 fields × crop years 2020-2026; key field_id, year)
**Year convention:** `year` is the **crop year**, which is the USGS water year, Oct 1 of year-1 to Sep 30 of year. The winter of Nov 2024 to Apr 2025 belongs to crop year 2025, together with the 2025 cash crop.
- Crop year 2027 (data for Oct 2026 only) is not written.
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
| green_up_doy | int16 | first day of year (≥ DOY 60) of calendar `year` that starts ≥ 15 consecutive living days (-1 = none) |
| n_clear_obs | int16 | clear obs in the crop year |
| n_obs_spring, n_obs_fall | int16 | clear obs in the spring / fall windows *(extra)* |

**Winter cover detection** uses two windows:
- Fall: Oct 15 to Dec 15 of year-1, after the previous crop is harvested.
- Spring: Mar 15 to May 10 of year, before the new crop canopy (corn and soy fields have median NDVI of about 0.23-0.27 until mid-May).

How each window is scored:
- **s** is the second-highest `live_px_share` over the window's clear observations. If the window has only one observation, s is that value. Using the second-highest makes s robust to a single noisy scene.
- Fall observations count only after the field's NDVI minimum between Sep 15 and Nov 30, which marks senescence or harvest. Standing green crops and late soybeans therefore do not count.
- `winter_cover` is true when at least 2 clear observations in the spring window, or at least 2 post-harvest observations in the fall window, have a cell-median NDVI ≥ 0.30.
- Of the field-years flagged as covered, 88% are detected in spring and 49% in fall; some are detected in both.

| crop year | 2020* | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| % fields with winter cover (NDVI 0.30) | 1.0 | 4.2 | 2.2 | 1.0 | 4.7 | 1.7 | 4.7 |
| sensitivity: threshold 0.25 | 11.6 | 39.1 | 19.3 | 20.6 | 38.5 | 13.4 | 29.1 |
| sensitivity: threshold 0.35 | 0.2 | 3.0 | 1.5 | 0.6 | 3.1 | 1.2 | 3.1 |
| median bare days (0.30) | 81* | 231 | 241 | 235 | 237 | 238 | 239 |
| median bare days Apr-Jun / Oct-Dec | 63 / - | 51 / 92 | 68 / 83 | 57 / 86 | 58 / 89 | 59 / 87 | 62 / 87 |
| median green-up DOY | 156 | 142 | 159 | 148 | 155 | 150 | 153 |

\* 2020 spring only, partial year.

What the table shows:
- The 0.30 results sit in the expected Iowa range, from low single digits to about 10%.
- 10.5% of fields show cover in at least one of 2021-2026, and 4.7% in at least two.
- 0.35 gives nearly the same answer as 0.30, so the detected covers are robust green-ups. Example: 75 fields in spring 2021 rose from 0.30 to 0.41 NDVI in late April, then dropped in early May at termination.
- **0.25 is not usable.** Residue and soil sit at NDVI 0.21-0.25, so that threshold flags 12-39% of fields.

By previous and current crop: corn → soy (the cereal-rye-before-soy niche) runs 0.5-3.5%, and corn → corn runs 1-9.6% (2024).

**Seasonal curves look right.** Median NDVI of clear observations on corn (C) and soy (S) field-years, by month:

| Crop | Jan | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov |
|---|---|---|---|---|---|---|---|---|---|---|
| Corn | .22 | .23 | .23 | .27 | .61 | .89 | .88 | .60 | .28 | .23 |
| Soy | .22 | .22 | .22 | .26 | .42 | .85 | .90 | .50 | .25 | .24 |

Corn greens up earlier, in June, and soy peaks later, in August. Median green-up DOY is 150 for corn and 157 for soy.

## `hls_vs_modis.json`
Compares HLS field living share with MODIS 13Q1 living share on row-crop pixels (`cover_huc12_8day.parquet`), per focus HUC-12 and per 16-day composite window. A pair needs at least 30 HLS field observations and a MODIS valid_frac of at least 0.5.

| Comparison | n | r | bias (MODIS - HLS) | Notes |
|---|---|---|---|---|
| All pairs | 2,253 | 0.945 | +0.079 | RMSE 0.167; same living/bare class 93.7% of the time |
| Whole focus area | 241 | 0.951 | | |
| Mean NDVI | | 0.986 | +0.019 | |
| Fall window | | 0.84 | +0.04 | |
| Spring window | | 0.36 | +0.11 | |
| MAM (Mar-May) | | | +0.15 | MODIS May living 0.38 vs HLS 0.09 |

MODIS reads greener, as expected:
- MODIS composites keep the highest-NDVI day of the 16 (maximum-value compositing).
- A 250 m pixel mixes in edges, waterways and early weeds.
- So MODIS bare share understates spring bare soil, and HLS is the better source for the spring leak window.

## Caveats
- **PC's HLS holdings are incomplete.** For 2023, NASA CMR lists 85 HLSS30 and 79 HLSL30 T15TUG granules with cloud cover ≤ 80. PC returns 42 S30 and 53 L30 that intersect the focus bbox. 2020-21 L30 holdings are also thin (22-25 per year).
  - Getting the rest from LP DAAC needs Earthdata login, which is not required here.
  - Observation density is still 32-53 clear observations per field-year from 2021 on.
- A field cell is a 16 ha grid square, not a surveyed field polygon. Neighbouring cells are not independent.
- Cover-crop detection cannot see a cover that was seeded late and terminated before Mar 15 without fall growth. It also misses one that never reaches a cell-median NDVI of 0.30 (small rye). The percentages are lower bounds on adoption and upper bounds on "no living roots".
- Fmask misses some thin cloud and haze. Those observations read low NDVI and count as bare, which is conservative for cover.
- Soils come from 90 m gNATSGO mukeys with dominant-component attributes, and slope from smoothed NASADEM 30 m, via the cdl agent's p07.

## Deviations from contract
- Extra columns are marked *(extra)* above.
- Living is decided on the cell-median NDVI ≥ 0.30 (the pixel share at least 0.5), not the cell-mean NDVI. The mean NDVI is still stored in `ndvi`.
- `field_month.bare_frac` and `living_frac` are day-weighted shares from the interpolated daily status, not shares of observations. `n_obs` is the observation count.
- `field_year.year` is the crop year (water year). `field_month` uses calendar year.
- `-1` is the sentinel for an unknown int16 value.

## Provenance
- HLS v2.0 L30/S30: https://planetarycomputer.microsoft.com/api/stac/v1 (collections `hls2-l30`, `hls2-s30`); NASA LP DAAC HLS, doi:10.5067/HLS/HLSL30.002 and 10.5067/HLS/HLSS30.002
- USDA NASS CDL 2016-2025: `data/raw/cdl/cdl_<year>_basins.tif` (cdl agent: PC `usda-cdl` 2016-2021 and NASS national zips 2022-2025). Focus selection used PC `usda-cdl` 2021 directly.
- SSURGO/gNATSGO via the cdl agent (`soils_mukey.parquet`, `mukey_90m.tif`); NASADEM slope (`slope_30m.tif`).
- WBD HUC-12: `huc12.parquet` (hydro, p01).
