# Module `context`: NASS yields, county polygons, NEX-GDDP-CMIP6 future climate and analogs

Owner files: `pipeline/context_nass.py`, `pipeline/context_counties.py`, `pipeline/context_climate.py`,
`data/nass_county_yields.parquet`, `data/nass_iowa_aggregates.parquet`, `data/counties.geojson`, `data/climate_future.json`, this note.
Raw caches: `data/raw/nass/`, `data/raw/census/`, `data/raw/nex_gddp/` (about 1 GB, mostly the CONUS daily subsets).

## Re-run

```
PY="<project>/.venv/bin/python"
"$PY" pipeline/context_nass.py            # ~3-12 min the first time (streams 1.1 GB gz); instant from cache. --refresh re-streams
"$PY" pipeline/context_counties.py        # seconds
"$PY" pipeline/context_climate.py --pc-check   # ~20 min the first time (558 NCSS requests, 8 threads); ~2 s from cache
                                         # (without --pc-check the PC comparison is still filled in from its cache in data/raw/nex_gddp/pc_check/)
```
`context_climate.py` caches per-file subsets in `data/raw/nex_gddp/ncss/` and per-model-year indices in
`data/raw/nex_gddp/indices/*.npz`. To recompute the indices, delete the `indices/` folder; to re-download, delete `ncss/` as well.
It reads `data/weather_annual.parquet` (conf module) when present, only for a cross-check block.

---

## 1. `data/nass_county_yields.parquet` (3,171 rows) and `data/nass_iowa_aggregates.parquet` (279 rows)

Source: the USDA NASS QuickStats public bulk file `qs.crops_20261114.txt.gz` (link taken from https://www.nass.usda.gov/datasets).
The file is streamed through gzip and filtered line by line, so the full file is never written to disk. Only the
3,584 matching raw rows are cached, in `data/raw/nass/ia_yield_rows.tsv`.
Filter: STATE_ALPHA=IA, SOURCE_DESC=SURVEY, STATISTICCAT_DESC=YIELD, UNIT_DESC=BU / ACRE, SHORT_DESC in
{`CORN, GRAIN - YIELD, MEASURED IN BU / ACRE`, `SOYBEANS - YIELD, MEASURED IN BU / ACRE`}, years 2008-2024,
REFERENCE_PERIOD_DESC=YEAR (drops in-season forecasts), DOMAIN_DESC=TOTAL.

| column | meaning |
|---|---|
| county_fips | `nass_county_yields`: 5-digit FIPS, real counties only. `nass_iowa_aggregates`: pseudo keys `19000` = Iowa state; `19D<asd>` = crop-reporting district; `19C<asd>` = "OTHER (COMBINED) COUNTIES" in that district (`19C99` = statewide, county_name "Other (combined) counties, statewide") |
| county_name | title case |
| year | int |
| crop | `corn` (grain) or `soybeans` |
| yield_bu_ac | float, bu/acre |
| agg_level | `nass_county_yields`: always `COUNTY` (3,171 rows). `nass_iowa_aggregates`: `COUNTY_OTHER_COMBINED` (29), `DISTRICT` (216), `STATE` (34) |
| asd_code, asd | NASS agricultural statistics district (crop-reporting district). The tile is mostly in Central, `50` |
| value_raw, cv_pct, nass_load_time, source | provenance |

Both files have identical columns. Since the verifier pass, **`nass_county_yields.parquet` holds only real counties** (99 counties), as the
contract requires; state, district and other-combined rows moved to `nass_iowa_aggregates.parquet`. Key (county_fips, year, crop) is unique in both (0 duplicates).

Sanity:
- County rows: corn n=1,599 (99 counties), mean 180.6, range 44.5-240.9; soybeans n=1,572, mean 53.2, range 24.6-70.5.
- Iowa state yields match published NASS values: corn 2012 = 137 (drought), 2020 = 177 (derecho), 2024 = 211; soybeans 2021 = 63.
- 14 tile counties: 454 of 476 county-crop-years are present. The 22 missing rows are NASS disclosure suppressions,
  rolled into "other (combined) counties": 2019 Warren corn; 2020 Jasper, Marion, Marshall (both crops); 2021 Hamilton corn,
  Warren (both crops); 2024 Dallas corn, Grundy, Hardin, Jasper, Madison, Warren (both crops), Marshall soybeans.
  2024 has the fewest county estimates statewide (73 corn, 68 soybean counties).
- District rows only exist through 2019 in the bulk file. NASS stopped publishing district yields after that.

## 2. `data/counties.geojson` (14 features, 19 kB, EPSG:4326)

Source: Census cartographic boundary file `cb_2023_us_county_500k.zip`. It keeps every county whose polygon intersects
the exact HLS UTM square (`tile_bounds_utm`, EPSG:32615). Polygons are simplified with `shapely.coverage_simplify` (tolerance 0.001 deg, about 100 m, which keeps the
shared borders topologically consistent) and coordinates are rounded to 1e-5 deg.
Properties: `fips` (key), `name`, `state_abbr`, `state_name`, `statefp`, `area_km2` (EPSG:5070), `frac_in_tile` (share of
the county inside the UTM tile square), `share_of_tile` (share of the tile area in that county; these sum to 1.000). Both shares are
computed in EPSG:32615 against the UTM square (changed from the lon/lat bbox; max change 0.0024, e.g. Greene 0.0135 -> 0.0116).
Counties: Boone, Polk and Story (100% inside the tile); Dallas, Jasper, Marshall, Hamilton, Hardin (69-85%); Webster (33%);
Grundy, Marion, Warren, Madison, Greene (9-21%).
`web/data/counties.geojson` is a deliberate stripped copy (name, fips, state_abbr, frac_in_tile) written by the frontend's
`pipeline/frontend_counties.py`; re-run that script to pick up the updated frac_in_tile (frontend-owned, not written here).

## 3. `data/climate_future.json` (61 kB)

### Data and access
- Dataset: NASA NEX-GDDP-CMIP6, daily, 0.25 deg, bias-corrected and statistically downscaled. Ensemble member r1i1p1f1.
- GCMs: **GFDL-ESM4, MRI-ESM2-0, ACCESS-CM2**. All three have historical, ssp245 and ssp585 runs on both servers.
- **Deviation from the brief (access path, not dataset):** the brief asked for the Planetary Computer (PC) copy. The PC NetCDFs are chunked
  as one full global day per chunk (1x600x1440, gzip and shuffle, about 0.67 MB each). Any read of a small box therefore pulls about 100 MB
  per variable-season. Measured throughput to the PC blob from here was about 5 MB/s, which made the full job (about 57 GB) take hours.
  The primary path is now **NASA NCCS THREDDS NetCDF Subset Service** (`https://ds.nccs.nasa.gov/thredds/ncss/grid/AMES/NEX/GDDP-CMIP6/...`).
  It subsets on the server, returning about 40 kB for a tile box and about 5-6 MB for a CONUS box per variable-season. It uses the latest file
  version per year, which was `_v2.0` for every file used.
  The PC path is still implemented as an automatic per-file fallback (`read_pc`: STAC lookup, then HTTP range reads of only the needed daily
  chunks, local zlib decompression and unshuffle, then the box subset). In this run the fallback was never needed: all 558 files came from NCCS.
- **Cross-check (`--pc-check`):** for MRI-ESM2-0 historical 2000 tasmax over May-Sep, the tile-mean daily series from NCCS v2.0 and from
  PC were **identical** (mean |diff| = 0.0 K over 153 days). Stored in `sources.pc_vs_nccs_check`.
  Only that one variable-year was compared. Other variables or models could differ between v1 (PC) and v2.0 (NCCS) files.
- Seasonal windows downloaded: tasmax and tasmin May 1-Sep 30, pr Apr 1-Aug 31 (153 days each in every calendar). Every
  model-year had all 153 days, so there are 0 failures.
- Units: K converted to degC, pr kg m-2 s-1 multiplied by 86400 to get mm/day.

### Tile indices (per year)
These are computed per 0.25-deg cell and then averaged over the **20 cells whose centres lie inside `tile_bounds_lonlat`**:
lon -94.125 to -93.125 (5 cells) and lat 41.625 to 42.375 (4 cells).

| key | units | definition |
|---|---|---|
| gdd_may_sep | degC-days | sum of ((clip(Tx,10,30)+clip(Tn,10,30))/2 - 10), May-Sep. Same 86/50 method as `conf_weather.py` |
| hdd30_jul_aug | degC-days | single-sine degree-days above 30C from Tn/Tx, Jul-Aug. **Same definition as conf's `weather_annual.hdd30_jul_aug`** |
| hdd30tx_jul_aug | degC-days | sum of max(Tx-30, 0), Jul-Aug (Tmax-excess, the brief's original definition; about 4x the sine value). Used for analogs |
| days_tmax_gt30_jul_aug | days | count of Tx > 30C, Jul-Aug |
| prcp_amj, prcp_jja | mm | season totals |
| tmax_jul | degC | mean July Tx |

**Rename (verifier fix):** `hdd30_jul_aug` now means the same quantity in this file and in `data/weather_annual.parquet` (sine method).
The Tx-excess series that used to be called `hdd30_jul_aug` is now `hdd30tx_jul_aug`, and `hdd30sine_jul_aug` no longer exists.
Never apply an `hdd30tx` delta to an `hdd30` (sine/POWER) baseline. The cached `.npz` files keep the old internal names; the
mapping is in `npz_key()` in `context_climate.py`.
**Stale downstream file:** the current `web/data/climate.json` (not owned here) has historical `hdd30` around 80, so it was built from the
old Tx-excess key. If it is rebuilt from `hdd30_jul_aug` it will switch to the sine scale (around 19 historical, 50 in 2035-55). Either is
fine for the frontend's relative heat-path use, but its source key and units label must be stated, and it must not be mixed with POWER `hdd30` unless it is the sine series.

### JSON layout
- `per_year[model][scenario]` = {years:[...], <index>:[...]}. Historical covers 1995-2014 (20 years); ssp245 and ssp585 cover 2035-2055 (21 years).
- `summary[scenario][index]` = mmm_mean (mean of the 3 model means), per_model_mean, pooled_p10/p50/p90/sd over all model-years,
  and for the SSPs delta_vs_hist_mmm, delta_vs_hist_per_model and delta_vs_hist_range.
- `analogs` (object; the top-25 list is `analogs.cells`), `analogs_list` (the same 25 flattened to the web contract shape
  `[{lon,lat,state,label,distance}]`, state = 2-letter abbreviation), `power_comparison`, `region.tile_cells_lonlat`,
  `variables` (units and definitions), `sources`, `failures` ({}), `notes`.
- **Historical per-year values are model-years, not observed years.** The 1995-2014 'years' are free-running GCM years: their
  distribution matches reality but their sequence does not (ACCESS-CM2's '2012' is not the 2012 drought). Never join them with
  observed-year data (POWER, NASS, HLS, outcomes). Use the historical series only as a distribution or climatology, and the same for future years.

### Key numbers (tile, multi-model mean; ranges are across the 3 GCMs)
| index | 1995-2014 | 2035-55 SSP2-4.5 (delta) | 2035-55 SSP5-8.5 (delta) |
|---|---|---|---|
| gdd_may_sep | 1679 | 1893 (+214; +109 to +300) | 1931 (+252; +173 to +292) |
| hdd30_jul_aug (sine) | 18.8 | 50.1 (+31.3) | 50.9 (+32.1) |
| hdd30tx_jul_aug (Tx>30 excess) | 80 | 180 (+100; +49 to +176) | 183 (+103; +65 to +161) |
| days_tmax_gt30_jul_aug | 30.0 | 45.5 | 47.1 |
| prcp_amj (mm) | 329 | 343 (+14; +11 to +19) | 353 (+24; +19 to +32) |
| prcp_jja (mm) | 338 | 329 (-9; -25 to +10) | 339 (+1; -28 to +19) |
| tmax_jul (C) | 30.4 | 32.7 (+2.3; +1.6 to +3.6) | 32.8 (+2.4; +1.9 to +3.0) |

ACCESS-CM2 is the hot model and GFDL-ESM4 the mild one. By 2035-55 the two SSPs differ little, as expected this early.
- Historical model means agree closely (GDD 1674-1682). This is expected because the data are bias-corrected to GMFD.
- **POWER cross-check, 1995-2014 tile** (`power_comparison`). NEX minus POWER: GDD +87 (5%), hdd30 (sine, same key in both) -0.85 (NEX 18.8 vs POWER 19.65), days Tx>30 +6.1,
  tmax_jul +0.8 C, prcp_amj -19 mm, prcp_jja +0.8 mm. NEX is GMFD-based and POWER is MERRA-2-based, so their absolute levels differ.
  **Downstream should apply NEX deltas to POWER baselines**, not mix absolute values.

### Analog search (`analogs`)
- Candidates: every 0.25-deg lower-48 land cell (13,122 cells: centre inside a Census county polygon, AK/HI/territories excluded,
  data present in all models). Each cell's climate is the 1995-2014 mean of [gdd_may_sep, hdd30tx_jul_aug, prcp_amj, prcp_jja] (Tx-excess heat; the sine index is only computed for tile cells),
  using **all 20 years at full 0.25 deg** (no subsampling was needed). Per model, then averaged over the 3 GCMs.
- Target: the tile's 2035-2055 SSP2-4.5 multi-model mean (GDD 1893, hdd30tx 180, AMJ 343 mm, JJA 329 mm).
- Distance: standardised Euclidean, with each feature scaled by its spatial SD across the candidate cells
  (GDD 450, hdd30tx 130, AMJ 112, JJA 124). The top 25 are returned with lon/lat, state, county, label, distance, per-model distance and rank,
  km and direction from the tile centre, and the cell's own 1995-2014 climate.
- **Result:** all 25 analogs are in **northern/west-central Missouri (22) and NE Kansas (3)**, around Buchanan, Clay, Ray, Carroll, Saline
  and Platte counties in MO and Atchison and Leavenworth counties in KS. The weighted centroid is (-94.12, 39.38), **about 290 km due south** of the tile.
  Top distance is 0.075, 25th is 0.201. Across all cells, the 1st percentile is 0.36 and the median 2.23. The tile's own 1995-2014 climate is
  at distance 0.92 (rank 2,019), so the shift is substantial.
- **Robustness:**
  - Scaling by the tile's interannual SD instead (`sensitivity_interannual_scaling`) gives 17 of 25 of the same cells and the same
    centroid (MO 24, KS 1).
  - Per-model analogs differ a lot (`per_model`): GFDL-ESM4 points to southern Iowa and northern MO (164 km S), MRI-ESM2-0 to Kentucky
    (809 km SE, a wetter and warmer analog), and ACCESS-CM2 to eastern Kansas (470 km SW, hotter and drier).
  - The top-25 overlap between each single model and the multi-model result is 0, 2 and 0.
  - Present the MO/KS analog as the multi-model central estimate, and use the spread as the uncertainty.
- Method note: this is the "climate analog" idea (find places whose present climate matches a site's future), with a simple 4-variable
  growing-season feature set. Interannual variability, soils and day length are not matched.

### Caveats
- Only 3 GCMs and 1 ensemble member each. The spread understates CMIP6 uncertainty. The analog location depends strongly on the model.
- Tile means smooth out within-tile gradients (about 1 deg across). The 0.25-deg cells are coarse relative to fields.
- The `web/data/climate.json` contract (`scenarios.ssp245.{years,gdd,hdd30,prcp_amj}`, `analogs[{lon,lat,state,label,distance}]`) can be
  built directly from `per_year` (e.g. the multi-model mean per year) and `analogs_list`. This module does not write web files.
  Whoever builds it must say which heat key `hdd30` comes from (`hdd30_jul_aug` = sine, the POWER-comparable one, or `hdd30tx_jul_aug`).

## Verifier fixes (second pass)
- hdd30 rename in `climate_future.json`: `hdd30_jul_aug` = sine (matches POWER/conf), `hdd30tx_jul_aug` = Tx-excess. Only the JSON
  assembly changed. After undoing the rename, a diff against the previous JSON showed `per_year`, `summary`, `analogs` and `sources`
  were otherwise identical.
- `sources.pc_vs_nccs_check` is now filled whenever the cached PC file exists, even without `--pc-check` (no network call).
- `analogs_list` alias added, and a note added saying the per-year values are model-years.
- NASS: non-county rows were moved to `data/nass_iowa_aggregates.parquet`, and the statewide other-combined name was fixed.
- Counties: shares are now computed against the exact UTM square. Same 14 counties.
