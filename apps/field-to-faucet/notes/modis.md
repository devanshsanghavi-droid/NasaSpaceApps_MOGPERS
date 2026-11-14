# Module `modis`: watershed living-cover / bare-soil shares of row-crop land (NASA MODIS 13Q1)

Scripts: `pipeline/p08_modis_mask.py` (about 40 s), then `pipeline/p09_modis_cover.py` (about 5 min the first time;
about 40 s from cache, and later runs fetch only new composites), then `pipeline/p09b_hls_gapfill.py` (HLS gap-fill of
the 2025 MODIS gap: about 7 min of reads the first time, about 1 min from cache; it re-runs p09 at the end to merge).

## Provenance
- NASA MODIS Vegetation Indices 16-day 250 m, Collection 6.1, Terra **MOD13Q1** and Aqua **MYD13Q1**, from the Microsoft
  Planetary Computer: collection `modis-13Q1-061` (https://planetarycomputer.microsoft.com/dataset/modis-13Q1-061).
  The COG assets read are `250m_16_days_NDVI`, `250m_16_days_pixel_reliability` and
  `250m_16_days_composite_day_of_the_year`, from tiles **h10v04 + h11v04**. Only the basin window is read, about
  0.6 Mpx of each 23 Mpx tile. Upstream product: NASA LP DAAC (https://lpdaac.usgs.gov/products/mod13q1v061/).
- Tile check: the h10/h11 boundary (x = -7,783,654 m sinusoidal) crosses the Raccoon basin. It lies at about -94.2°
  at 42°N and about -93.5° at 41.5°N. h10v04 holds 66,346 mask px (≈ 57% of the Raccoon mask). h11v04 holds 245,770 px
  (the rest of the Raccoon and nearly all of the Des Moines basin). Both basins are north of 40°N, so all of them is in v04.
- Row-crop mask: USDA NASS Cropland Data Layer, 30 m, from PC `usda-cdl` (`usda_cdl:type=cropland`, 15 items per year,
  2016-2021; https://planetarycomputer.microsoft.com/dataset/usda-cdl).
- HUC-12 polygons: `data/processed/huc12.parquet` (hydro module, from USGS WBD).
- 2025 gap-fill: NASA HLS v2 (Harmonized Landsat Sentinel-2) `hls2-l30` + `hls2-s30` on Planetary Computer
  (https://planetarycomputer.microsoft.com/dataset/hls2-l30, .../hls2-s30; upstream LP DAAC HLSL30/HLSS30 v2.0).
  Bands B04 (red), B05 (L30 NIR) / B8A (S30 NIR), Fmask. 7 MGRS tiles chosen by greedy set cover of the mask
  (T15TUG, T15TUH, T15TVG cover the Raccoon; + T15TVH, T15TUJ, T14TQP, T15TVJ for the Des Moines; 100% / 99.8% of masked
  px). 1,526 scenes with scene cloud ≤ 75% in Jun 24-Dec 4 of 2023 and 2024 and Jun 1-Dec 8 2025; all read, 0 failures.

## Method
1. **Mask (p08).** A CDL 30 m pixel counts as *persistent row crop* when it is row crop in ≥ 5 of the 6 years 2016-2021.
   Row-crop codes: corn 1, 12, 13, 241; soy 5, 239, 240; other row crops 2, 3, 4, 6, 10, 11, 41, 42, 43. These are the same
   letters C/S/R as `shared/.../notes/cdl.md`.
   - This binary layer is averaged with GDAL `average` resampling onto the MODIS sinusoidal grid (231.656 m pixels,
     0.0537 km², equal-area). The result is `rowcrop_frac`.
   - Pixels with `rowcrop_frac ≥ 0.75` whose centre falls in a basin HUC-12 form the mask.
   - Each pixel also gets a HUC-12 index and a basin id (pixel-centre rasterization).
2. **Classification (p09), per composite, over masked pixels.**
   - valid = reliability 0 (good) or 1 (marginal), with NDVI not fill.
   - snow = reliability 2 (snow/ice). cloud = reliability 3. fill = anything else, including a missing tile.
   - living = valid & NDVI ≥ 0.30. bare = valid & NDVI < 0.30.
   - Sensitivity thresholds: 0.25 and 0.35.
   - Every pixel has equal weight. Pixels are not weighted by `rowcrop_frac`.
3. **Dating.** Terra composites start on DOY 1, 17, 33, … and Aqua on DOY 9, 25, …, so together they give an 8-day
   cadence.
   - `date` = composite start + 8 days, the mid-point of the 16-day window. It is unique per basin.
   - `obs_date` = composite start + the mean of the per-pixel `composite_day_of_the_year` offset over valid pixels. This is
     the actual mean acquisition date: on average 7.70 d after the start (range 0-15 d).
   - `obs_date_obs` is the same, taken over valid + snow pixels.
4. **Daily series, interpolated (NOT causal).** Living and bare shares are linearly interpolated in time on `obs_date`.
   Only composites with `valid_frac ≥ 0.30` and `tile_cover_frac ≥ 0.90` are used ("usable").
   - `snow_share` is interpolated on `obs_date_obs`. It uses composites where (valid + snow) / px ≥ 0.30.
   - `gap_days` is the spacing of the two bracketing composites used. `filled = gap_days > 24`.
   - This series looks ahead: day t uses the next composite, whose pixels were acquired a median ~16 d later and which
     is published later still. Use it for description and seasonal summaries, **not as a forecasting feature**.
5. **Daily series, causal as-of.** On day t the as-of value is the latest usable composite already published:
   `avail_date = composite_start + 16 + 3 d latency ≤ t`. Carried forward, never interpolated.
   `age_days = t − (composite_start + 15)` (days since the window's last day; 4 on the day it becomes available);
   `asof_stale = age_days > 40`. Snow uses its own usable set (`snow_age_days`). `bare_nonsnow_asof` =
   bare_share_asof × (1 − snow_share_asof). HLS gap-fill composites take part like MODIS ones (`asof_src`).
6. **2025 gap-fill with HLS (p09b).** For each scene, each masked MODIS pixel is sampled at 4 sub-points (centre ± PX/4)
   on the 120 m COG overview (overview level 1; HLS overviews are NEAREST, so each is a 30 m point sample).
   - Sub-point clear = Fmask bits 1-4 (cloud, adjacent, shadow, snow) all 0 and valid reflectance; snow = bit 4 only;
     a pixel is clear on a scene when ≥ 3 sub-points are clear and none is cloudy. NDVI = mean over clear sub-points.
   - Composites use exactly the MOD13Q1/MYD13Q1 16-day windows; per pixel the **maximum** NDVI over clear scenes
     (maximum-value compositing, like MODIS); valid = ≥ 1 clear scene. 1,526 scenes give 32-74 scenes per gap window (14-77 over all windows).
   - Calibration: pixel pairs (HLS MVC NDVI, MODIS NDVI) where both are valid on the same window, composite starts
     Jun 25-Nov 30 of 2023 and 2024, plus the 2025 composites bracketing the gap (Terra A2025177, Jun 26; Nov 17):
     38 composites × 2 basins, 11.2 M pixel pairs. An empirical quantile mapping HLS → MODIS NDVI (201 quantiles) is
     applied per pixel before the 0.25/0.30/0.35 thresholds. Results below.
   - Gap windows (composite_start 2025-07-04 .. 2025-11-09, 17 per basin) with no MODIS composite get the calibrated HLS
     composite, `gapfill_src = 'hls'`, `sensor = 'hls'`, `n_tiles = 0`, `n_scenes` = scenes used.
7. **Year summaries (coverage-checked).** A day is *supported* for bare/living when it lies between two usable
   composites ≤ 45 d apart (MODIS or HLS). For the bare & snow-free metrics, a day is supported when the snow series
   is (snow_gap ≤ 45 d) and either bare/living is supported or snow_share ≥ 0.5. Seasonal metrics need ≥ 90% of the
   window's days supported, annual ones ≥ 95% of the year; otherwise NaN. Interpolation across long gaps no longer
   counts as data. `nov_living_mean`, `apr_living_mean`, `winter_living_mean` need ≥ 3 usable composites in the month(s).

## Outputs
### `data/raw/modis/` (raw, gitignored)
- `mask_grid.npz`: arrays `rowcrop_frac`, `huc_idx` (-1 = outside), `basin_id` (0 none, 1 raccoon, 2 desmoines), `mask`.
  Also stored: `transform`, `shape` (1346 × 1332), `offset` (global MODIS row 21952, col 52433), `huc12`, `crs`.
- `rowcrop_frac.tif`, `huc_idx.tif`: GeoTIFFs in sinusoidal projection, for inspection.
- `cdl/rowcrop_<year>.npz`: packed 30 m row-crop bitmasks, cached.
- `cache/<product>.A<yyyyddd>.<tile>.npz`: NDVI, reliability and DOY at the masked pixels for each item. There are 999
  files, 247 MB in total.
- `hls/<HLS item id>.npz`: per HLS scene, at the masked pixels inside that MGRS tile: ndvi (×1e4, int16), n_clear,
  n_snow, n_cloud, n_nod (sub-point counts 0-4). 1,526 files, 86 MB.

### `data/processed/cover_basin_8day.parquet`: 1,036 rows (501 MODIS + 17 HLS composites × 2 basins)
Key: basin, date. Composite dates (mid-points) run from 2015-06-10 to 2026-10-24.

| column | meaning |
|---|---|
| basin | 'raccoon' / 'desmoines' |
| date | composite mid-date (start + 8 d) |
| composite_start | first day of the 16-day window |
| sensor | 'terra' (MOD13Q1) / 'aqua' (MYD13Q1) / 'hls' (gap-fill) |
| n_tiles | number of the 2 MODIS tiles present (0 on HLS rows) |
| obs_date, obs_date_obs | mean per-pixel acquisition date over valid pixels / over valid + snow pixels (timestamp) |
| n_px, n_valid | masked pixels in basin (raccoon 107,985; desmoines 204,131) / valid pixels |
| tile_cover_frac | share of the basin's masked px whose tile exists for this composite |
| valid_frac, snow_frac, cloud_frac, fill_frac | shares of n_px |
| living_share, bare_share | shares of **valid** px with NDVI ≥ / < 0.30 (they sum to 1) |
| snow_share | snow / (valid + snow) |
| bare_nonsnow_share | bare / (valid + snow): bare **and** snow-free share of observable cropland |
| mean_ndvi | mean NDVI over valid px (unitless) |
| living_share_t25, bare_share_t25, living_share_t35, bare_share_t35 | same at NDVI 0.25 / 0.35 |
| gapfill_src | 'modis' / 'hls' (calibrated HLS composite in a window with no MODIS composite) |
| n_scenes | HLS scenes in the window (HLS rows only; NaN for MODIS) |
| avail_date | composite_start + 19 d: first day the composite may be used causally |

### `data/processed/cover_basin_daily.parquet`: 8,310 rows
Key: basin, date. Both basins 2015-07-01 to the run date (2026-11-14), 4,155 d each. The interpolated columns are NaN
after the last usable composite (Raccoon after 2026-10-05, Des Moines after 2026-10-20; `gapfill_src = 'none'`); the
as-of columns run to the run date.

Interpolated (centred, NOT causal) columns, unchanged:
- `living_share`, `bare_share`, and the `_t25` / `_t35` variants of each
- `mean_ndvi`, `snow_share`
- `bare_nonsnow_share` = bare_share × (1 − snow_share)
- `gap_days`, `filled` (bool, gap > 24 d; also True where there is no interpolation), `snow_gap_days`
- `gapfill_src` (new): 'modis', 'hls' (a bracketing composite is HLS), 'interp' (gap > 24 d), 'none' (past the end)

Causal as-of columns (new; see Method 5):
- `bare_share_asof`, `living_share_asof`, `snow_share_asof`, `bare_nonsnow_asof`
- `age_days` (t − last day of the as-of composite window; min 4, median 8, max 88), `snow_age_days`
- `asof_stale` (bool, age_days > 40): 2-4% of days, all in snowy/cloudy winters (none in 2025 thanks to HLS)
- `asof_src`: 'modis' / 'hls'

15.5-16.6% of days are `filled`, nearly all in Dec-Mar snow/cloud periods (and Dec 2025).
Note for the model module: `gapfill_src` describes the interpolated series; the source of the as-of value is `asof_src`.

### `data/processed/cover_huc12_8day.parquet`: 144,789 rows
Key: huc12, date. 289 HUC-12s × 501 MODIS composites. One HUC-12 has no masked pixel and is absent.

Columns: huc12, basin, date, sensor, n_px, n_valid, valid_frac, living_share, bare_share, snow_share,
bare_nonsnow_share, mean_ndvi, and (new) `tile_cover_frac` (share of the HUC-12's masked px whose MODIS tile exists),
`composite_start`, `avail_date`. Where `tile_cover_frac < 0.5` (222 rows: HUC-12s in h10v04 on the 3 partial-tile
dates) valid_frac and all shares are NaN (unknown), not 0. The median HUC-12 has 1,040 masked px.
- HUC-12 as-of series (not stored, to keep files small): `pd.merge_asof(days, h8[usable].sort_values('avail_date'),
  left_on='date', right_on='avail_date', by='huc12')` with usable = valid_frac ≥ 0.3; age = date − (composite_start + 15).
- No HLS rows here (MODIS only), so MODIS-vs-HLS comparisons on this file stay clean.

### HLS gap-fill files (p09b)
- `data/processed/cover_hls_8day.parquet`: 240 rows = 60 HLS composites × 2 basins × `calib` ('raw', 'qm' = quantile
  mapped). Same share columns as cover_basin_8day, plus n_scenes, in_gap. Covers the calibration windows too.
- `data/processed/cover_hls_huc12_8day.parquet`: 4,913 rows, calibrated HLS shares per HUC-12 for the 17 gap windows
  (same columns as cover_huc12_8day minus composite_start/avail_date).
- `data/processed/cover_hls_calibration.json`: agreement statistics, quantile map, tiles, scene counts.

### `data/processed/modis_basin_year.parquet`: 24 rows
Key: basin, year (2015-2026).

Columns:
- Spring (Mar 15-Jun 15) and fall (Sep 15-Dec 15): `{spring,fall}_bare_mean` (plus `_t25` / `_t35`),
  `{spring,fall}_bare_nonsnow_mean`, `{spring,fall}_bare_nonsnow_days`, `{spring,fall}_filled_days`, and (new)
  `{spring,fall}_supported_days`, `{spring,fall}_hls_days`.
- `bare_nonsnow_days` = Σ over days of daily bare_share × (1 − snow_share), the "cropland-equivalent bare & snow-free
  days". Only for years with ≥ 95% supported days.
- `days_majority_bare_nonsnow` = days with bare_share ≥ 0.5 and snow_share < 0.5 (same coverage rule).
- `winter_living_mean` (Dec of the previous year to Feb), `nov_living_mean`, `apr_living_mean` (≥ 3 usable composites),
  with `winter_n_composites`, `{nov,apr}_n_composites`, `{nov,apr}_n_hls`.
- `n_composites`, `n_hls_composites`, `n_lowvalid_composites`, `filled_days`, `supported_days`,
  `supported_days_bare_nonsnow`, `hls_days`.
- NaN by the coverage rule: fall 2022 Des Moines (81 of 92 days supported: an 89-day Dec-Feb gap starts Dec 5),
  bare_nonsnow_days 2019 Raccoon, apr_living_mean 2022 (< 3 usable April composites), the incomplete years 2015/2026.

## Sanity stats
**Mask.**
- Raccoon: 167,488 basin px (8,988 km², vs WBD 9,004). Mean persistent-row-crop fraction 0.736. 107,985 px (64.5%) pass ≥ 0.75.
- Des Moines: 301,814 px (16,197 km², vs 16,225). Mean fraction 0.759. 204,131 px (67.6%) pass.

**Seasonal cycle.** Monthly mean bare_share over composites with valid_frac ≥ 0.3. It behaves as expected: high Nov-May,
zero Jul-Aug.

| month | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Raccoon | .98 | .99 | .98 | .88 | .61 | .06 | .00 | .00 | .04 | .56 | .92 | .97 |
| Des Moines | .97 | .99 | .99 | .92 | .66 | .08 | .00 | .00 | .04 | .60 | .93 | .97 |
| snow_share Des Moines (all composites) | .56 | .53 | .12 | .02 | 0 | 0 | 0 | 0 | 0 | .00 | .03 | .31 |

**Spring bare share by year** (Mar 15-Jun 15, NDVI 0.30):

| year | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Raccoon | .62 | .66 | .71 | .72 | .68 | .62 | .76 | .71 | .61 | .66 | .62 |
| Des Moines | .66 | .70 | .74 | .73 | .72 | .68 | .78 | .77 | .67 | .67 | .64 |

- Year-to-year SD is 0.04-0.05.
- The two basins move together: r = 0.94 across years; the daily series correlate at r = 0.997.
- High years are cold/late springs (2018, 2019 wet and delayed planting, 2022). Low years are warm springs (2016, 2021,
  2024). This interannual signal is mostly **green-up timing**, which is weather-driven (weeds, grassed waterways and
  field-edge mixing, early crop emergence), not management.
- Fall bare (Sep 15-Dec 15) ranges 0.57 (2019, late harvest) to 0.78 (2020, early dry harvest) in MODIS years.
  **Fall 2025 (HLS gap-fill for Sep 15-Nov 24): 0.705 Raccoon / 0.704 Des Moines** (t25 0.43 / t35 0.83 Raccoon), with
  70 / 63 of 92 days HLS-bracketed and all 92 supported. bare_nonsnow_days 2025: 175 Raccoon / 186 Des Moines. The
  earlier 0.686 / 0.631 and ~182 were straight-line interpolation across Jul 8-Dec 30 and are withdrawn.

**HLS vs MODIS calibration (cover_hls_calibration.json).** 38 overlapping composites per basin (2023: 18, 2024: 18,
2025: 2), living share at NDVI 0.30, basin level:

| | raw HLS | quantile-mapped | leave-one-year-out mapping |
|---|---|---|---|
| all (n = 76) bias HLS − MODIS / r / RMSE | +0.055 / 0.987 / 0.100 | −0.001 / 0.989 / 0.062 | −0.002 / 0.977 / 0.086 |
| fall starts Sep 15-Nov 30 (n = 32) | +0.127 / 0.952 / 0.154 | −0.003 / 0.947 / 0.094 | −0.006 / 0.883 / 0.132 |
| Raccoon (n = 38) | +0.042 / 0.991 / 0.078 | −0.010 / 0.989 / 0.062 | −0.012 / 0.978 / 0.087 |
| Des Moines (n = 38) | +0.068 / 0.987 / 0.119 | +0.008 / 0.990 / 0.061 | +0.007 / 0.978 / 0.085 |

- Pixel NDVI (11.2 M pairs): r 0.96, raw bias +0.023, MAE 0.054. Raw HLS reads greener than MODIS in fall
  (HLS max-of-many-scenes at 30 m point samples vs MODIS 250 m composites); the mapping lowers HLS NDVI by
  ~0.02-0.05 in the 0.25-0.50 range, which is where the 0.30 threshold sits. Mapping is needed and applied.
- Out-of-sample (leave-one-year-out) fall error is ~0.13 RMSE in living share per composite, no bias; the seasonal
  mean over ~11 composites is much tighter. The pre-gap Jun 26 2025 composite agrees to 0.001; the post-gap Nov 17 2025
  composite reads 0.115 (HLS) vs 0.157 (MODIS, valid_frac 0.45) in the Raccoon.

**Low-quality composites.** valid_frac < 0.3: raccoon 47, desmoines 60 of 501. All but 5 fall in Dec-Feb (Jan 44,
Feb 41, Dec 17, Mar 2, Apr 2, Nov 1, counting both basins).

**Threshold sensitivity is large in spring.**
- In April-May, the median NDVI of masked pixels is 0.24-0.30. 37-71% of valid pixels lie in [0.25, 0.35).
- Spring bare mean ranges 0.24-0.52 at t25, 0.61-0.78 at t30 and 0.76-0.88 at t35.
- Interannual rankings mostly survive. Correlation of spring bare across years, t30 vs t25 / t35: raccoon 0.85 / 0.89,
  desmoines 0.71 / 0.86.
- Use the shares as a **relative index** (timing / interannual anomaly). Do not use them as an absolute "% of fields bare".

**Winter living share vs cover crops.**
- Dec-Feb living_share (valid_frac ≥ 0.3) is 0.7-7%. It is highest in mild, snow-poor winters (2016: 3.6/7.2%; 2024:
  5.0/4.2% Des Moines/Raccoon).
- November living share is 2-14% in 2015-2024 (MODIS, 3-4 composites each). 2025: 12.2% Raccoon (3 HLS + 1 MODIS
  composites) / 13.9% Des Moines (3 HLS; the MODIS Nov 17 composite has valid_frac < 0.3 there), i.e. HLS-based and
  carrying the calibration error above. April living share is 1-20%, low in a cold April (2018: ≈1%) and high in a
  warm one (2024, 2026).
- Iowa cover-crop adoption is on the order of single-digit % of cropland, so the magnitude is the right order. But the
  signal is **dominated by weather and phenology, not by cover crops**:
  - It tracks temperature and snow.
  - At 250 m, a pixel mixes field edges, waterways and farmsteads.
  - Most cereal rye has NDVI < 0.30 in Dec-Feb.
  - MODIS max-value compositing biases NDVI upward.
- At t25, winter living is 12-20%, which is clearly mixed-pixel or soil background.
- Do **not** present the MODIS winter living share as a cover-crop adoption estimate. HLS at the field scale (fields
  module) is the right tool for that.

## Caveats and deviations
- **2025 MODIS gap, filled with HLS (see BLOCKERS.md).** PC has no 13Q1 composites after Terra A2025177
  (start Jun 26) until Terra A2025321 (start Nov 17): the first missing one is Aqua A2025185 (start Jul 4), the last
  Aqua A2025313 (start Nov 9), 17 windows. They are filled with quantile-mapped HLS composites (`gapfill_src = 'hls'`).
  HLS rows differ from MODIS in sensor, resolution and compositing; the calibration error above applies to them, and
  their snow detection (Fmask) is not MODIS reliability = 2. Without p09b, the gap stays honest: as-of values go stale
  and fall-2025 summaries are NaN.
- **Partial tiles.** h10v04 is missing for 3 composites (2026-01-04, 2026-10-16, 2026-10-24). They are kept in the 8-day
  file with `tile_cover_frac` and left out of the daily series, so the Raccoon interpolated series ends 2026-10-05 and
  its as-of value on 2026-11-14 is 30 days old. HUC-12 rows of h10v04 HUC-12s are NaN on those dates.
- **Look-ahead.** The interpolated daily columns are centred (non-causal). Forecast features must use the `*_asof`
  columns (or `avail_date` in the 8-day files).
- **Static mask (deviation from CONTRACTS.md).** The contract says "row-crop pixels (CDL that year)". As instructed, we use
  one persistent 2016-2021 mask, because PC CDL ends in 2021. Pixels that left or entered row crop after 2021 are not
  updated.
- **250 m mixed pixels.** The threshold of ≥ 75% persistent row crop still lets up to 25% of a pixel be roads, waterways,
  grass or farmsteads. This raises off-season NDVI and creates the spring ambiguity around 0.30.
- **Compositing.** MOD13Q1 picks the best (roughly maximum-NDVI, low view angle) clear observation in 16 days, so it
  leans green and is early in green-up. Each composite's pixels come from different days. `obs_date` gives their mean.
- **Snow.** Reliability = 2 only when the whole 16-day window was snow-covered. Partial snow can lower NDVI and inflate
  bare_share. Use `bare_nonsnow_share` or `snow_share` from POWER SNODP as a cross-check.
- **Clouds.** Clouds are only flagged by reliability 3. Shares are computed over valid pixels and assume the cloudy pixels
  look like the clear ones.
- **Reservoir.** The Des Moines basin outlet is below Saylorville Reservoir. Land-cover effects on the river there are
  lagged and damped.
