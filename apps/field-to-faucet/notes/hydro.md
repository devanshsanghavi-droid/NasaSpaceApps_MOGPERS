# Module `hydro`: river nitrate/flow, POWER weather, map context

Scripts (run in order; all re-runnable, raw downloads cached in `data/raw/<source>/`):
```
python3 pipeline/p01_wbd.py          # basins + HUC-12s (already run; see script docstring)
python3 pipeline/p02_nwis.py         # ~20 s
python3 pipeline/p03_power.py        # ~10 s warm, ~1 min cold
python3 pipeline/p04_web_context.py  # ~15 s cold
```
All outputs were generated on 2026-11-14.

## data/processed/nwis_daily.parquet: 8,124 rows, key (site, date)
- Covers 2 sites × 4,062 days, 2015-10-01..2026-11-13. It is a full calendar grid: a missing day is a row with NaN.
- Today's partial-day dv value is dropped.
- Source: USGS NWIS daily values `https://waterservices.usgs.gov/nwis/dv/?format=json&sites=05484500,05482000&parameterCd=99133,00060&statCd=00003`.
  - It is fetched per water year and cached in `data/raw/nwis/dv_wy<YYYY>.json`.
  - Water years that end within the last 400 days are re-fetched on every run, because provisional data get revised.
- IV fill: `https://waterservices.usgs.gov/nwis/iv/` over the last 120 days.
  - Readings are grouped by the local date in each NWIS timestamp, and a day is kept only when it has at least 80 of 96 readings.
  - On this run the fill was **not needed: 0 days were filled**. The only recent dv gap, 05482000 nitrate on 2026-07-27, has just 32 IV readings.

| column | type / units | meaning |
|---|---|---|
| site | str | `05484500` Raccoon R. at Van Meter (basin `raccoon`); `05482000` Des Moines R. at 2nd Ave (basin `desmoines`) |
| date | date32 | local calendar day, as NWIS reports it |
| no3_mgL | mg/L as N | daily mean, parameter 99133 (nitrate + nitrite) |
| no3_qual | str | NWIS qualifiers joined with commas: `A` approved, `P` provisional, `e` estimated. `[4]` is NWIS's "no matching qualifier" code; on dv it marks days computed from incomplete data |
| q_cfs | ft³/s | daily mean discharge, parameter 00060 |
| q_qual | str | same codes as no3_qual. `A,e` appears on 1,096 days, mostly ice-affected winter flow estimates |
| load_kgN_day | kg N/day | no3_mgL × q_cfs × 2.4466. NaN if either input is missing |
| src | str | contract field: source of the nitrate value, `dv` or `iv`. None when nitrate is missing |
| no3_src, q_src | str | the source of each variable on its own |

Qualifier counts for nitrate: A 7,018, P 318, `A,[4]` 137, `P,[4]` 10, `A,e` 2. Provisional data start in roughly mid-2025.

### Sanity stats
- 2025-06-01, Raccoon: **12.7 mg/L** (A). This matches the contract.
- Maximum nitrate:
  - Raccoon: 18.6 mg/L on 2026-05-28. The 2025 maximum was 18.4 mg/L on 2025-06-07.
  - Des Moines: 17.0 mg/L on 2025-06-12.
- Maximum flow:
  - Raccoon: 34,900 cfs (2019).
  - Des Moines: 27,300 cfs (2018).

Coverage (% of days with a value) and days with nitrate > 10 mg/L, by site and year. "No3 %" is nitrate coverage; "Q %" is flow coverage.

| year | Raccoon No3 % | Raccoon Q % | Raccoon days >10 | Raccoon max | Des Moines No3 % | Des Moines Q % | Des Moines days >10 | Des Moines max |
|---|---|---|---|---|---|---|---|---|
| 2015 (Oct-Dec) | 93.5 | 100 | 81 | 15.1 | 0.0 | 100 | 0 | – |
| 2016 | 99.2 | 100 | 162 | 13.9 | 75.1 | 100 | 99 | 14.9 |
| 2017 | 98.4 | 100 | 67 | 14.6 | 97.3 | 100 | 66 | 14.0 |
| 2018 | 91.5 | 100 | 19 | 10.7 | 90.1 | 100 | 0 | 9.7 |
| 2019 | 95.1 | 100 | 15 | 10.9 | 94.2 | 99.7 | 0 | 8.3 |
| 2020 | 97.3 | 100 | 2 | 10.7 | 98.1 | 98.4 | 0 | 9.5 |
| 2021 | 93.7 | 100 | 0 | 6.8 | 87.7 | 100 | 0 | 6.5 |
| 2022 | 93.2 | 100 | 42 | 14.4 | 98.1 | 100 | 18 | 11.7 |
| 2023 | 97.8 | 100 | 6 | 13.1 | 88.2 | 100 | 0 | 9.9 |
| 2024 | 98.4 | 100 | 68 | 16.1 | 88.5 | 100 | 61 | 16.1 |
| **2025** | 97.5 | 100 | **115** | 18.4 | 78.6 | 100 | **105** | 17.0 |
| 2026 (to 11-13) | 94.0 | 100 | **176** | 18.6 | 99.1 | 100 | **158** | 14.8 |

Notes on the table:
- **Raccoon in 2025:** the first day over 10 mg/L was 2025-03-26, and the river was still over 10 on 2025-12-31.
- **Des Moines in 2025:** days over 10 run from 2025-04-09 to 2025-08-06. Jan-Feb 2025 is a gap (no nitrate data), so read "days > 10" as a lower bound wherever coverage is low.
- **2026 so far:** missing nitrate days at Raccoon are 2026-04-21..05-05 and four days in late May, which is during the spring peak.

## data/processed/power_*.parquet (NASA POWER, daily, community AG)
- Source: `https://power.larc.nasa.gov/api/temporal/daily/point` (POWER API v2.10.3, times in LST).
  - Each cell is queried at its centre: one 2015-2025 request (cached for good) plus one current-year request (re-fetched when its cache is more than 20 h old).
  - Raw JSON is in `data/raw/power/p<lat>_<lon>_<y0>_<y1>.json`. Fill value -999 is converted to NaN.
- **Grid**, verified by probing on 2016-06-10..12:
  - Lat 42.20 ≠ 42.30, and 42.30 = 42.70, so there is a boundary at 42.25.
  - Lon -94.05 ≠ -94.08, and -94.05 = -93.45 ≠ -93.42, so there are boundaries at -94.0625 and -93.4375.
  - The cells are therefore MERRA-2 0.5° lat × 0.625° lon, with centres at lat k·0.5 and lon -180 + k·0.625.
  - cell_id is `p<lat:.2f>_<lon:.3f>`, e.g. `p42.00_-94.375`, the same format as shared/central_iowa_pipeline.
- **21 cells** intersect the basins.
  - Raccoon: 10 cells with weight > 0, of which 7 carry 99.7% of the weight.
  - Des Moines: 17 cells with weight > 0.
  - A few cells have tiny weights (< 0.003). `p44.50_-95.625` only touches the basin and has weight 0 for both basins after rounding. These cells are kept so that every HUC-12 maps to a cell.
- Header `sources`: MERRA2 for 2015-2025. The 2026 request adds GEOSIT (near-real-time meteorology on the same grid) and FLASHFlux (solar).
- **Last date: 2026-11-11.** POWER lags about 3 days. Trailing dates where any cell lacks PRECTOTCORR, T2M or GWETROOT are trimmed.

| file | rows | content |
|---|---|---|
| power_cells.parquet | 21 | cell_id, lat, lon (centre), elev_m (POWER), area_km2 (EPSG:5070), w_raccoon, w_desmoines. w_basin = area(cell ∩ basin) / area(basin), so it sums to 1 per basin |
| huc12_cell.parquet | 461 | huc12, cell_id, weight = area(cell ∩ HUC-12) / area(HUC-12). It sums to 1 per HUC-12; pieces under 1e-4 are dropped. All 290 HUC-12s are mapped |
| power_daily_cells.parquet | 90,993 (21 × 4,333 days) | cell_id, date, then the variables below (float32) |
| power_daily_basin.parquet | 8,666 (2 × 4,333) | basin, date, the same variables area-weighted with w_basin (renormalised over non-NaN cells), and w_valid = weight share of cells with PRECTOTCORR (1.0 on every day) |

Variables (POWER AG units):

| variable | units |
|---|---|
| T2M, T2M_MAX, T2M_MIN | °C |
| PRECTOTCORR | mm/day (bias-corrected MERRA-2 precipitation) |
| GWETROOT, GWETTOP | 0-1 (root-zone / surface soil wetness) |
| SNODP | cm (snow depth) |
| PRECSNOLAND | mm/day (snowfall over land) |
| RH2M | % |
| ALLSKY_SFC_SW_DWN | MJ/m²/day, on POWER's 1° solar grid, so neighbouring cells share values |
| WS2M | m/s |

Missing values:
- PRECSNOLAND is missing from **2026-10-01** onward in every cell (0.97% of rows), during the GEOS-IT period.
- ALLSKY_SFC_SW_DWN is missing on 2026-09-07, 2026-11-10 and 2026-11-11.
- Everything else is 0% missing.

### Sanity stats (basin area-weighted)

| year | Raccoon precip (mm) | Raccoon GWETROOT | Des Moines precip (mm) | Des Moines GWETROOT |
|---|---|---|---|---|
| 2015 | 1,082 | 0.531 | 956 | 0.486 |
| 2016 | 877 | 0.563 | 956 | 0.555 |
| 2017 | 770 | 0.494 | 778 | 0.518 |
| 2018 | 1,055 | 0.526 | 1,132 | 0.555 |
| 2019 | 973 | 0.603 | 1,015 | 0.648 |
| 2020 | 588 | 0.498 | 634 | 0.536 |
| 2021 | 700 | 0.456 | 686 | 0.453 |
| 2022 | 585 | 0.439 | 598 | 0.445 |
| 2023 | 657 | 0.441 | 661 | 0.442 |
| 2024 | 809 | 0.455 | 899 | 0.477 |
| 2025 | 860 | 0.471 | 868 | 0.477 |
| 2026 (to 11-11) | 909 | 0.495 | 829 | 0.483 |

These match known history:
- 2018-2019 were wet, and GWETROOT peaked in 2019.
- 2020-2023 were drought years, with low nitrate in 2021.
- Wetting resumed from 2024.
- The 2016 and 2024-2026 nitrate spikes follow dry-to-wet transitions, the classic flushing pattern.

## web/data (map context)
- **rivers.geojson** (37 features, 66 KB): props `name` (null for unnamed connectors) and `order` (NHDPlus Strahler stream order).
  - Source: USGS NHD MapServer layer 4 "Flowline - Small Scale" (NHDPlus V2, 1:100k), `https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/4/query`.
  - Query: `StreamOrde >= 4 OR GNIS_NAME IN (main rivers)` within the basins' bbox, giving 2,988 reaches (cached in `data/raw/nhd/`).
  - Clipped to the basins plus a 500 m buffer. The main rivers also continue through a lon/lat box (-94.0, 41.45, -93.57, 41.70) so they reach the gauges, the Raccoon/Des Moines confluence and the DMWW intakes in Des Moines.
  - Merged per (name, order), simplified at 120 m in EPSG:5070. Pieces shorter than 3 km are dropped.
  - Layer 6 "Flowline - Large Scale" returned HTTP 504 (see BLOCKERS.md).
  - **Name fix:** NHDPlus V2 labels the Raccoon main stem below the North/South Raccoon confluence, at (-93.9667, 41.5438) just above the Van Meter gauge, as "North Raccoon River". Order ≥ 6 reaches east of the confluence are relabelled "Raccoon River", its GNIS name.
  - Named rivers include the Des Moines, East Fork Des Moines, Boone, North/Middle/South Raccoon and Raccoon rivers, plus order-4 creeks.
- **counties.geojson** (30 counties: 23 IA, 7 MN; 10 KB): props `name`, `state` (IA/MN) and `fips` (5-digit GEOID).
  - Source: Census cartographic boundary file `https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip`.
  - Kept: counties with at least 0.5% of their area inside the basins.
  - Simplified at 100 m. Iowa county lines are mostly straight, so the file is small.
- **places.json** (24 entries): `{name, lon, lat, kind ('city'|'town'|'intake'), basin|null, geoid|site, source}`.
  - Kinds: Des Moines (city); West Des Moines plus 17 Iowa and 3 Minnesota towns inside the basins (town); the two intake gauges (intake).
  - Town coordinates are Census 2023 Gazetteer internal points (`https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_gaz_place_{19,27}.txt`).
  - The "intake" points are the USGS gauge locations, a proxy for the Des Moines Water Works intakes on each river, and are labelled as such.
  - The focus-area towns are not chosen yet, because `focus_area.json` belongs to the fields module. Filter by `basin`, or by distance to the focus bbox.

## Caveats for downstream modelers
- **Saylorville Reservoir** lies upstream of 05482000 on the Des Moines River. Its storage delays and smooths nitrate and flow there and lets in-reservoir uptake/denitrification act, so driver-to-river relations at 05482000 need longer lags than at the free-flowing Raccoon. The Des Moines basin (16,225 km² from WBD HUC-12s) extends into Minnesota.
- **POWER resolution:** POWER is MERRA-2 reanalysis at roughly 50 km (0.5 × 0.625°), plus GEOS-IT for recent months.
  - It is **not** IMERG and not a gauge network. Convective storm peaks are smoothed, and daily totals use the LST day.
  - With 10 to 17 cells per basin, basin means are robust, but per-HUC-12 precipitation is just a blend of 1-4 cells.
  - The GEOS-IT period (most recent months) may have a small level shift against MERRA-2. Check before trusting live-period anomalies.
- **NWIS:**
  - Data from about mid-2025 are provisional (`P`) and can be revised. The re-run re-fetches the last 400 days.
  - Gaps are left as NaN, with nothing interpolated. When counting exceedance days, use coverage or count only observed days.
  - The 2015 Des Moines nitrate record starts in 2016.
- **Loads:** load_kgN_day uses daily means (Σc·q/n ≠ mean(c)·mean(q)). That is fine at daily scale; for annual loads sum only days that have both values, or fill gaps with a model.
- **Load units:** 1 cfs·mg/L = 2.4466 kg/day. Mean 2025 load on observed days was 18,700 t N/yr-equivalent at Raccoon and 46,200 at Des Moines.
