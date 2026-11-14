# Module `modis`: watershed living-cover / bare-soil shares of row-crop land (NASA MODIS 13Q1)

Scripts: `pipeline/p08_modis_mask.py` (about 40 s), then `pipeline/p09_modis_cover.py` (about 5 min the first time;
about 40 s from cache, and later runs fetch only new composites).

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
     the actual mean acquisition date: on average 7.2 d after the start (range 0-15 d).
   - `obs_date_obs` is the same, taken over valid + snow pixels.
4. **Daily series.** Living and bare shares are linearly interpolated in time on `obs_date`. Only composites with
   `valid_frac ≥ 0.30` and `tile_cover_frac ≥ 0.90` are used.
   - `snow_share` is interpolated on `obs_date_obs`. It uses composites where (valid + snow) / px ≥ 0.30.
   - `gap_days` is the spacing of the two bracketing composites used. `filled = gap_days > 24`.
5. **Year summaries.** Computed from the daily series. A season counts only if ≥ 90% of its days exist.

## Outputs
### `data/raw/modis/` (raw, gitignored)
- `mask_grid.npz`: arrays `rowcrop_frac`, `huc_idx` (-1 = outside), `basin_id` (0 none, 1 raccoon, 2 desmoines), `mask`.
  Also stored: `transform`, `shape` (1346 × 1332), `offset` (global MODIS row 21952, col 52433), `huc12`, `crs`.
- `rowcrop_frac.tif`, `huc_idx.tif`: GeoTIFFs in sinusoidal projection, for inspection.
- `cdl/rowcrop_<year>.npz`: packed 30 m row-crop bitmasks, cached.
- `cache/<product>.A<yyyyddd>.<tile>.npz`: NDVI, reliability and DOY at the masked pixels for each item. There are 999
  files, 247 MB in total.

### `data/processed/cover_basin_8day.parquet`: 1,002 rows (501 composites × 2 basins)
Key: basin, date. Composite dates (mid-points) run from 2015-06-10 to 2026-10-24.

| column | meaning |
|---|---|
| basin | 'raccoon' / 'desmoines' |
| date | composite mid-date (start + 8 d) |
| composite_start | first day of the 16-day window |
| sensor | 'terra' (MOD13Q1) / 'aqua' (MYD13Q1) |
| n_tiles | number of the 2 tiles present |
| obs_date, obs_date_obs | mean per-pixel acquisition date over valid pixels / over valid + snow pixels (timestamp) |
| n_px, n_valid | masked pixels in basin (raccoon 107,985; desmoines 204,131) / valid pixels |
| tile_cover_frac | share of the basin's masked px whose tile exists for this composite |
| valid_frac, snow_frac, cloud_frac, fill_frac | shares of n_px |
| living_share, bare_share | shares of **valid** px with NDVI ≥ / < 0.30 (they sum to 1) |
| snow_share | snow / (valid + snow) |
| bare_nonsnow_share | bare / (valid + snow): bare **and** snow-free share of observable cropland |
| mean_ndvi | mean NDVI over valid px (unitless) |
| living_share_t25, bare_share_t25, living_share_t35, bare_share_t35 | same at NDVI 0.25 / 0.35 |

### `data/processed/cover_basin_daily.parquet`: 8,245 rows
Key: basin, date. Des Moines: 2015-07-01 to 2026-10-20 (4,130 d). Raccoon: 2015-07-01 to 2026-10-05 (4,115 d).

Columns:
- `living_share`, `bare_share`, and the `_t25` / `_t35` variants of each
- `mean_ndvi`, `snow_share`
- `bare_nonsnow_share` = bare_share × (1 − snow_share)
- `gap_days`, `filled` (bool, gap > 24 d), `snow_gap_days`

18-19% of days are `filled`. Most of them fall in Dec-Mar snow/cloud periods, plus the 2025 gap below.

### `data/processed/cover_huc12_8day.parquet`: 144,789 rows
Key: huc12, date. 289 HUC-12s × 501 composites. One HUC-12 has no masked pixel and is absent.

Columns: huc12, basin, date, sensor, n_px, n_valid, valid_frac, living_share, bare_share, snow_share,
bare_nonsnow_share, mean_ndvi. The median HUC-12 has 1,040 masked px.

### `data/processed/modis_basin_year.parquet`: 24 rows
Key: basin, year (2015-2026).

Columns:
- Spring (Mar 15-Jun 15) and fall (Sep 15-Dec 15): `{spring,fall}_bare_mean` (plus `_t25` / `_t35`),
  `{spring,fall}_bare_nonsnow_mean`, `{spring,fall}_bare_nonsnow_days`, `{spring,fall}_filled_days`.
- `bare_nonsnow_days` = Σ over days of daily bare_share × (1 − snow_share), the "cropland-equivalent bare & snow-free
  days". Only for complete years.
- `days_majority_bare_nonsnow` = days with bare_share ≥ 0.5 and snow_share < 0.5.
- `winter_living_mean` (Dec of the previous year to Feb), `nov_living_mean`, `apr_living_mean`.
- `n_composites`, `n_lowvalid_composites`, `filled_days`.

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
- Fall bare (Sep 15-Dec 15) ranges 0.57 (2019, late harvest) to 0.79 (2020, early dry harvest).

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
- November living share is 2-16%. April living share is 1-20%, low in a cold April (2018: ≈1%) and high in a warm one
  (2024, 2026).
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
- **2025 data gap (see BLOCKERS.md).** PC has no 13Q1 composites from 2025-07-12 to 2025-11-16. The daily series is
  linearly interpolated across Jul 8 to Dec 30, 2025 (`filled`). Fall-2025 summaries are NaN.
- **Partial tiles.** h10v04 is missing for 3 composites (2026-01-04, 2026-10-16, 2026-10-24). They are kept in the 8-day
  file with `tile_cover_frac` and left out of the daily series, so the Raccoon daily series ends 2026-10-05.
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
